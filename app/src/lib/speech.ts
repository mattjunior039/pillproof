// Speech out: the browser's speechSynthesis (on-device voices). Speech in: record with MediaRecorder,
// decode to 16 kHz mono and transcribe in the browser with Moonshine (never a cloud speech service).
export const canSpeak = () => typeof speechSynthesis !== "undefined";

export function speak(text: string, rate = 0.95): Promise<void> {
  if (!canSpeak()) return Promise.resolve();
  speechSynthesis.cancel();
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text.replace(/1-800-222-1222/g, "1, 800, 2 2 2, 12 22"));
    u.rate = rate;
    u.lang = "en-US";
    u.onend = u.onerror = () => resolve();
    speechSynthesis.speak(u);
  });
}

export const stopSpeaking = () => canSpeak() && speechSynthesis.cancel();

export const canRecord = () => !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

export interface Recording { stop(): Promise<Float32Array>; cancel(): void }

export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const rec = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start();
  const done = () => stream.getTracks().forEach((t) => t.stop());
  return {
    stop: () => new Promise((resolve, reject) => {
      rec.onstop = async () => {
        done();
        try { resolve(await to16k(new Blob(chunks, { type: rec.mimeType }))); } catch (e) { reject(e); }
      };
      rec.stop();
    }),
    cancel: () => { rec.onstop = null; if (rec.state !== "inactive") rec.stop(); done(); },
  };
}

async function to16k(blob: Blob): Promise<Float32Array> {
  const buf = await blob.arrayBuffer();
  const ctx = new AudioContext();
  const audio = await ctx.decodeAudioData(buf);
  await ctx.close();
  const off = new OfflineAudioContext(1, Math.ceil(audio.duration * 16000), 16000);
  const src = off.createBufferSource();
  src.buffer = audio;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0).slice();
}
