import { speak } from "../../api/client";

let current: HTMLAudioElement | null = null;

export function playBase64(data: string, mime: string): Promise<void> {
  current?.pause();
  const audio = new Audio(`data:${mime};base64,${data}`);
  current = audio;
  return audio.play();
}

export async function speakEnglish(text: string): Promise<void> {
  const response = await speak(text, "en");
  if (!response.audio_wav_base64) {
    throw new Error("Синтез речи недоступен");
  }
  await playBase64(response.audio_wav_base64, "audio/wav");
}
