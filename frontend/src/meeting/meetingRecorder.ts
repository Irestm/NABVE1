import {
  createMeetingRecording,
  finishMeetingRecording,
  getMeetingRecording,
  uploadMeetingRecordingChunk,
} from "../api/client";
import type { MeetingRecording } from "../types";
import type { MeetingCaptureSnapshot, MeetingCaptureState } from "./types";

// Mirrors core/config.py Settings.meeting_recording_max_duration_seconds'
// default (2h30m). The server is the actual source of truth — it
// independently re-measures duration via ffprobe and rejects anything over
// its own configured limit regardless of what the client thinks — this is
// just the client-side auto-stop/warning trigger, kept in sync by
// convention rather than by a shared source.
const MAX_DURATION_MS = (2 * 3600 + 30 * 60) * 1000;
const DURATION_WARNING_LEAD_MS = 5 * 60 * 1000;
const CHUNK_TIMESLICE_MS = 5000;
const STATUS_POLL_INTERVAL_MS = 2000;

export class MicrophoneAccessError extends Error {}

interface MixResult {
  stream: MediaStream;
  micOnly: boolean;
  cleanup: () => void;
}

async function acquireMicStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new MicrophoneAccessError("Микрофон недоступен в этом окружении.");
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    console.error("Failed to acquire the microphone stream:", error);
    throw new MicrophoneAccessError("Доступ к микрофону не предоставлен.");
  }
}

// System/meeting audio is best-effort by design (see the module's
// architecture notes, section 3): any failure here — declined, unsupported
// platform, no matching source, or (in Electron) no
// setDisplayMediaRequestHandler registered — falls back to mic-only rather
// than blocking the recording. The only hard blocker is acquireMicStream
// above.
async function acquireSystemAudioStream(): Promise<MediaStream | null> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    return null;
  }
  try {
    const displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: true,
    });
    // Video is only ever requested because getDisplayMedia's underlying
    // picker (browser or, in Electron, the OS-native one wired up in
    // frontend/electron/main.ts) requires it — this module records audio
    // only, so the video track is stopped immediately and never touched
    // again.
    displayStream.getVideoTracks().forEach((track) => track.stop());
    const audioTracks = displayStream.getAudioTracks();
    if (audioTracks.length === 0) {
      return null;
    }
    return new MediaStream(audioTracks);
  } catch (error) {
    // Best-effort by design (see the comment above this function) — a
    // declined share is a normal, expected outcome here, not a bug, but
    // still worth a trace for the genuinely broken cases (e.g. an
    // Electron display-media handler misconfiguration).
    console.error("Failed to acquire system/meeting audio; falling back to mic-only:", error);
    return null;
  }
}

// Mixes mic + optional system audio into the single stream that gets
// recorded — never saved as separate tracks. Both sources run through their
// own GainNode into a shared DynamicsCompressorNode so neither one can
// swamp the other, per the module's design.
function mixStreams(micStream: MediaStream, systemStream: MediaStream | null): MixResult {
  const audioContext = new AudioContext();
  const destination = audioContext.createMediaStreamDestination();
  const compressor = audioContext.createDynamicsCompressor();
  compressor.connect(destination);

  const micGain = audioContext.createGain();
  micGain.gain.value = 1.0;
  audioContext.createMediaStreamSource(micStream).connect(micGain).connect(compressor);

  if (systemStream) {
    const systemGain = audioContext.createGain();
    // Attenuated slightly relative to the mic by default so the local
    // speaker's own voice doesn't get buried under remote participants.
    systemGain.gain.value = 0.85;
    audioContext.createMediaStreamSource(systemStream).connect(systemGain).connect(compressor);
  }

  return {
    stream: destination.stream,
    micOnly: systemStream === null,
    cleanup: () => {
      void audioContext.close();
    },
  };
}

/**
 * Owns the whole client-side meeting-recording lifecycle: acquiring and
 * mixing audio, streaming it to the backend in chunks, and polling for the
 * backend's processing/transcription outcome — see MeetingCaptureState.
 * Deliberately framework-free (no React) so the visual layer, designed
 * separately, can wrap it however it needs to (a hook, a store, ...).
 */
export class MeetingRecorderController {
  private state: MeetingCaptureState = "idle";
  private recordingId: number | null = null;
  private micStream: MediaStream | null = null;
  private systemStream: MediaStream | null = null;
  private mix: MixResult | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private uploadedBytes = 0;
  private micOnly = false;
  private audioSourceWarning: string | null = null;
  private durationWarning: string | null = null;
  private errorMessage: string | null = null;
  private startedAt = 0;
  // Frozen at the elapsed duration as of the moment recording actually
  // stopped — getSnapshot() must not keep counting wall-clock time through
  // "stopping"/"processing"/"done", or a future timer UI built on this
  // controller would show the clock still running after the mic is off.
  private frozenElapsedMs = 0;
  private elapsedTimer: ReturnType<typeof setInterval> | null = null;
  private statusPollTimer: ReturnType<typeof setInterval> | null = null;
  private uploadQueue: Promise<void> = Promise.resolve();

  constructor(private readonly onSnapshot?: (snapshot: MeetingCaptureSnapshot) => void) {}

  getSnapshot(): MeetingCaptureSnapshot {
    return {
      state: this.state,
      recordingId: this.recordingId,
      elapsedMs: this.state === "recording" ? Date.now() - this.startedAt : this.frozenElapsedMs,
      micOnly: this.micOnly,
      uploadedBytes: this.uploadedBytes,
      audioSourceWarning: this.audioSourceWarning,
      durationWarning: this.durationWarning,
      error: this.errorMessage,
    };
  }

  async start(contextLabel?: string | null): Promise<void> {
    if (this.state !== "idle" && this.state !== "done" && this.state !== "error") {
      return;
    }
    this.errorMessage = null;
    this.audioSourceWarning = null;
    this.durationWarning = null;
    this.uploadedBytes = 0;
    this.frozenElapsedMs = 0;
    this.setState("requesting");

    let micStream: MediaStream;
    try {
      micStream = await acquireMicStream();
    } catch (error) {
      this.errorMessage =
        error instanceof MicrophoneAccessError
          ? error.message
          : "Не удалось получить доступ к микрофону.";
      this.setState("error");
      return;
    }
    this.micStream = micStream;

    const systemStream = await acquireSystemAudioStream();
    this.systemStream = systemStream;
    if (!systemStream) {
      this.audioSourceWarning =
        "Не удалось захватить звук встречи — запись продолжится только с микрофона.";
    }

    let recordingId: number;
    try {
      recordingId = await createMeetingRecording(contextLabel);
    } catch (error) {
      console.error("Failed to create a meeting recording:", error);
      this.errorMessage = "Нет связи с ядром ассистента — не удалось начать запись.";
      this.cleanupStreams();
      this.setState("error");
      return;
    }
    this.recordingId = recordingId;

    this.mix = mixStreams(micStream, systemStream);
    this.micOnly = this.mix.micOnly;

    const recorder = new MediaRecorder(this.mix.stream);
    this.mediaRecorder = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        this.enqueueChunkUpload(event.data);
      }
    };
    recorder.onstop = () => {
      void this.handleRecorderStopped();
    };

    recorder.start(CHUNK_TIMESLICE_MS);
    this.startedAt = Date.now();
    this.setState("recording");
    this.startElapsedTimer();
  }

  async stop(): Promise<void> {
    if (this.state !== "recording") {
      return;
    }
    this.frozenElapsedMs = Date.now() - this.startedAt;
    this.stopElapsedTimer();
    this.setState("stopping");
    this.mediaRecorder?.stop();
  }

  /** For component unmount / app-close safety nets — tears everything down
   * without attempting to save. Prefer stop() for the normal user flow. */
  dispose(): void {
    this.stopElapsedTimer();
    this.stopStatusPolling();
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.onstop = null;
      this.mediaRecorder.stop();
    }
    this.cleanupStreams();
  }

  private enqueueChunkUpload(chunk: Blob): void {
    if (this.recordingId === null) {
      return;
    }
    const recordingId = this.recordingId;
    // Chunks must land in order; chaining onto a shared promise serializes
    // uploads instead of racing them, since MediaRecorder can fire
    // `ondataavailable` again before the previous chunk's request settles.
    this.uploadQueue = this.uploadQueue
      .then(() => uploadMeetingRecordingChunk(recordingId, chunk))
      .then((sizeBytes) => {
        this.uploadedBytes = sizeBytes;
        this.emit();
      })
      .catch((error: unknown) => {
        console.error("Meeting recording chunk upload failed:", error);
        this.errorMessage = "Не удалось передать часть записи на сервер.";
        this.forceStopIntoError();
      });
  }

  private startElapsedTimer(): void {
    this.elapsedTimer = setInterval(() => {
      const elapsed = Date.now() - this.startedAt;
      if (elapsed >= MAX_DURATION_MS) {
        void this.stop();
        return;
      }
      if (elapsed >= MAX_DURATION_MS - DURATION_WARNING_LEAD_MS) {
        this.durationWarning = "До достижения максимальной длительности записи осталось 5 минут.";
      }
      this.emit();
    }, 1000);
  }

  private stopElapsedTimer(): void {
    if (this.elapsedTimer !== null) {
      clearInterval(this.elapsedTimer);
      this.elapsedTimer = null;
    }
  }

  private async handleRecorderStopped(): Promise<void> {
    this.cleanupStreams();
    try {
      await this.uploadQueue;
    } catch {
      // Already surfaced through enqueueChunkUpload's own error handling.
    }
    if (this.state === "error") {
      return;
    }
    if (this.recordingId === null) {
      this.errorMessage = "Внутренняя ошибка: у записи нет идентификатора.";
      this.setState("error");
      return;
    }

    this.setState("processing");
    try {
      await finishMeetingRecording(this.recordingId, this.micOnly);
    } catch (error) {
      console.error("Failed to finish a meeting recording:", error);
      this.errorMessage = "Не удалось завершить запись на сервере.";
      this.setState("error");
      return;
    }
    this.pollUntilFinished(this.recordingId);
  }

  private pollUntilFinished(recordingId: number): void {
    this.statusPollTimer = setInterval(() => {
      void (async () => {
        let recording: MeetingRecording;
        try {
          recording = await getMeetingRecording(recordingId);
        } catch {
          return; // Transient network hiccup — retry on the next tick.
        }
        if (recording.status === "ready") {
          this.stopStatusPolling();
          this.setState("done");
        } else if (recording.status === "error") {
          this.stopStatusPolling();
          this.errorMessage = recording.error ?? "Не удалось обработать запись.";
          this.setState("error");
        }
      })();
    }, STATUS_POLL_INTERVAL_MS);
  }

  private stopStatusPolling(): void {
    if (this.statusPollTimer !== null) {
      clearInterval(this.statusPollTimer);
      this.statusPollTimer = null;
    }
  }

  private cleanupStreams(): void {
    this.mix?.cleanup();
    this.mix = null;
    this.micStream?.getTracks().forEach((track) => track.stop());
    this.micStream = null;
    this.systemStream?.getTracks().forEach((track) => track.stop());
    this.systemStream = null;
    this.mediaRecorder = null;
  }

  private forceStopIntoError(): void {
    if (this.state === "recording") {
      this.frozenElapsedMs = Date.now() - this.startedAt;
    }
    this.stopElapsedTimer();
    this.stopStatusPolling();
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      // The regular onstop handler would otherwise try to finish/save the
      // recording — this path means an upload already failed hard, so skip
      // straight to the error state instead.
      this.mediaRecorder.onstop = null;
      this.mediaRecorder.stop();
    }
    this.cleanupStreams();
    this.setState("error");
  }

  private setState(state: MeetingCaptureState): void {
    this.state = state;
    this.emit();
    // Gates Electron's close/quit confirmation dialog — no-op in a plain
    // browser, where window.assistantAPI is undefined (see
    // frontend/electron/preload.ts and main.ts's "before-quit" handler).
    const active = state === "recording" || state === "stopping";
    window.assistantAPI?.setRecordingActive?.(active);
  }

  private emit(): void {
    this.onSnapshot?.(this.getSnapshot());
  }
}
