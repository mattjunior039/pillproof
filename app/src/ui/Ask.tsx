import { useEffect, useRef, useState } from "preact/hooks";
import { SIZE_MB } from "../lib/device.ts";
import { shortName } from "../lib/schedule.ts";
import { askInChat, currentModel, go, useApp } from "../store.ts";
import { ReplyView } from "./Reply.tsx";

const EXAMPLES = ["What's next?", "Can I drink grapefruit juice?", "What if I miss a dose?", "What are the common side effects?"];

export function ModelBanner({ inSettings = false }: { inSettings?: boolean }) {
  const s = useApp();
  const m = s.model;
  if (s.settings.answerMode === "passages") return <p class="banner">Showing label sentences only (Settings → Answers).</p>;
  if (m.status === "crashed" || s.crash) return <p class="banner warn">This device shows label sentences only, because the answer model stopped working here. {s.crash}</p>;
  if (m.status === "unsupported") return <p class="banner">This browser can't run the answer model, so answers show the closest label sentences. {s.gpu?.reason}</p>;
  if (m.status === "loading") {
    return (
      <div class="banner">
        <p>Loading the answer model… {Math.round(m.progress * 100)}%</p>
        <progress value={m.progress} max={1} />
        <p class="small">Until it's ready, answers show label sentences.</p>
      </div>
    );
  }
  if (m.status === "error") return <p class="banner warn">{m.text} Answers show label sentences. {!inSettings && <button class="linklike" onClick={() => go("settings")}>Settings</button>}</p>;
  if (m.status === "off") {
    return (
      <p class="banner">
        Answers show the closest label sentences. For short plain-language answers, download the answer model once
        ({SIZE_MB[currentModel().size]} MB).{" "}
        {inSettings ? "Use the button below." : <button class="linklike" onClick={() => go("settings")}>Set up in Settings</button>}
      </p>
    );
  }
  return null;
}

export function Ask() {
  const s = useApp();
  const [q, setQ] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [s.chat.length, s.chat[s.chat.length - 1]?.reply]);

  const send = (text: string) => {
    const t = text.trim();
    if (!t || s.busy) return;
    setQ("");
    askInChat(t);
  };

  return (
    <section class="ask">
      <h1>Ask about a label</h1>
      <ModelBanner />
      {!s.chat.length && (
        <div>
          <p>Ask about any medicine on your list. Answers come only from its FDA label.</p>
          <div class="chips">{EXAMPLES.map((e) => <button class="chip" onClick={() => send(e)}>{e}</button>)}</div>
        </div>
      )}
      <ol class="chat" aria-live="polite">
        {s.chat.map((c) => (
          <li>
            <p class="q">{c.question}</p>
            {c.reply ? (
              <ReplyView reply={c.reply} onChoose={(m) => {
                const r = c.reply as Extract<typeof c.reply, { kind: "choose" }>;
                askInChat(r.question, { med: m, advice: r.advice });
              }} />
            ) : <p class="busy">{c.status}</p>}
          </li>
        ))}
      </ol>
      <div ref={end} />
      <form class="askbar" onSubmit={(e) => { e.preventDefault(); send(q); }}>
        <label for="ask-input" class="sr-only">Your question</label>
        <input id="ask-input" type="text" enterkeyhint="send" autocomplete="off" value={q} placeholder={s.meds.length ? `e.g. Can I take ${shortName(s.meds[0]).split(" ")[0]} with food?` : "Type a question"}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
        <button class="btn primary" type="submit" disabled={s.busy || !q.trim()}>Ask</button>
      </form>
    </section>
  );
}
