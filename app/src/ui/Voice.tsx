import { useEffect, useRef, useState } from "preact/hooks";
import { plainText } from "../lib/answer.ts";
import { ASR_MODEL, transcribe, warmAsr } from "../lib/ml.ts";
import { correctNames } from "../lib/names.ts";
import { ADVICE_LINE, NOT_COVERED, STANDING_LINE } from "../lib/router.ts";
import { shortName } from "../lib/schedule.ts";
import { canRecord, canSpeak, speak, startRecording, stopSpeaking, type Recording } from "../lib/speech.ts";
import { answer, get, saveSettings, useApp, type Reply } from "../store.ts";
import { ReplyView } from "./Reply.tsx";

type Phase = "idle" | "recording" | "transcribing" | "thinking" | "speaking";

const ASR_MB = { phone: 28, desktop: 63 };

/** What gets read aloud: the same words as on screen, minus links. */
export function spoken(r: Reply): string {
  switch (r.kind) {
    case "emergency": case "schedule": case "info": return r.text;
    case "choose": return `Which medicine is this about? ${r.meds.map(shortName).join(", or ")}. Tap one on the screen.`;
    case "label": return plainText(r.result, r.advice, ADVICE_LINE, STANDING_LINE, NOT_COVERED);
  }
}

export function Voice() {
  const s = useApp();
  const [phase, setPhase] = useState<Phase>("idle");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [err, setErr] = useState("");
  const [dl, setDl] = useState<string>("");
  const [typed, setTyped] = useState("");
  const rec = useRef<Recording | null>(null);
  const pressAt = useRef(0);
  const busy = useRef(false);
  const model = ASR_MODEL[s.tier];

  useEffect(() => () => { rec.current?.cancel(); stopSpeaking(); }, []);

  const respond = async (question: string, forced?: Parameters<typeof answer>[1]) => {
    setHeard(question);
    setPhase("thinking");
    setReply(null);
    try {
      const r = await answer(question, forced);
      setReply(r);
      if (get().settings.speakAnswers && canSpeak()) {
        setPhase("speaking");
        await speak(spoken(r));
      }
    } catch (e) {
      setErr(String((e as Error).message || e));
    }
    setPhase("idle");
  };

  // Hold to talk, or tap once to start and tap again to stop.
  const down = async () => {
    if (rec.current) return finish();
    if (busy.current) return;
    stopSpeaking();
    setErr("");
    pressAt.current = Date.now();
    busy.current = true;
    try {
      rec.current = await startRecording();
      setPhase("recording");
    } catch {
      busy.current = false;
      setErr("The microphone is blocked. Allow it in the browser settings, or type your question below.");
    }
  };

  const up = () => {
    if (rec.current && Date.now() - pressAt.current > 400) finish();
  };

  const finish = async () => {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    setPhase("transcribing");
    try {
      const audio = await r.stop();
      if (audio.length < 16000 * 0.4) { setPhase("idle"); setErr("That was too short. Hold the button while you speak."); return; }
      const text = correctNames(await transcribe(audio, model, (p) => setDl(p.total ? `${Math.round((100 * p.loaded) / p.total)}%` : "")), get().meds);
      setDl("");
      if (!text) { setPhase("idle"); setErr("I didn't catch that. Try again, or type below."); return; }
      await respond(text);
    } catch (e) {
      setPhase("idle");
      setErr(`Speech recognition failed: ${(e as Error).message || e}. You can type instead.`);
    } finally {
      busy.current = false;
    }
  };

  const enableVoice = async () => {
    setErr("");
    setDl("0%");
    try {
      await warmAsr(model, (p) => setDl(p.total ? `${Math.round((100 * p.loaded) / p.total)}%` : ""));
      await saveSettings({ voiceConsent: true });
    } catch (e) {
      setErr(`Couldn't download the speech model: ${(e as Error).message || e}`);
    }
    setDl("");
  };

  const label = { idle: "Hold to ask", recording: "Listening… let go (or tap) when done", transcribing: "Working out what you said…", thinking: "Looking in the label…", speaking: "Speaking… tap to ask again" }[phase];
  const voiceReady = s.settings.voiceConsent && canRecord();

  return (
    <section class="voice">
      <h1 class="sr-only">Voice</h1>
      {voiceReady ? (
        <button class={`holdbtn ${phase}`} aria-label={label}
          onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); down(); }}
          onPointerUp={up} onPointerCancel={up}
          onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); down(); } }}
          onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); up(); } }}
          onContextMenu={(e) => e.preventDefault()}>
          <span class="mic" aria-hidden="true">🎤</span>
          <span>{label}</span>
        </button>
      ) : (
        <div class="card">
          <p class="lead">Ask out loud and hear the answer.</p>
          {canRecord() ? (
            <>
              <p>Speech is turned into text on this device. The speech model downloads once (about {ASR_MB[s.tier]} MB); nothing you say leaves this device.</p>
              <button class="btn primary big" disabled={!!dl} onClick={enableVoice}>{dl ? (dl === "100%" ? "Getting ready…" : `Downloading… ${dl}`) : "Turn on voice"}</button>
            </>
          ) : <p>This browser can't record audio. Type your question below; answers are still read aloud.</p>}
        </div>
      )}
      {dl && voiceReady && <p class="small">Preparing speech model… {dl}</p>}
      {err && <p class="error" role="alert">{err}</p>}
      {heard && <p class="heard">You asked: <strong>{heard}</strong></p>}
      <div aria-live="polite" class="voice-reply">
        {reply && <ReplyView reply={reply} onChoose={(m) => reply.kind === "choose" && respond(reply.question, { med: m, advice: reply.advice })} />}
      </div>
      {phase === "speaking" && <button class="btn big" onClick={() => { stopSpeaking(); setPhase("idle"); }}>Stop speaking</button>}
      <form class="askbar" onSubmit={(e) => { e.preventDefault(); if (typed.trim() && (phase === "idle" || phase === "speaking")) { stopSpeaking(); respond(typed.trim()); setTyped(""); } }}>
        <label for="voice-type" class="sr-only">Type a question</label>
        <input id="voice-type" type="text" enterkeyhint="send" value={typed} placeholder="Or type a question" onInput={(e) => setTyped((e.target as HTMLInputElement).value)} />
        <button class="btn primary" type="submit">Ask</button>
      </form>
    </section>
  );
}
