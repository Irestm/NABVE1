// State machine for capturing a meeting recording client-side — see the
// module's architecture notes (idle -> requesting -> recording ->
// stopping/uploading -> processing -> done, with error reachable from any
// step). This file intentionally has no UI/React dependency: the visual
// layer (buttons, timer, waveform) is designed separately, on top of
// MeetingRecorderController's snapshot callback.
export type MeetingCaptureState =
  | "idle"
  | "requesting"
  | "recording"
  | "stopping"
  | "processing"
  | "done"
  | "error";

export interface MeetingCaptureSnapshot {
  state: MeetingCaptureState;
  recordingId: number | null;
  elapsedMs: number;
  micOnly: boolean;
  uploadedBytes: number;
  // Set once, at the start of a recording, if system/meeting audio
  // couldn't be captured — persists for the whole recording (distinct from
  // durationWarning, which comes and goes near the end of a long
  // recording, so the two must never overwrite one another).
  audioSourceWarning: string | null;
  durationWarning: string | null;
  error: string | null;
}
