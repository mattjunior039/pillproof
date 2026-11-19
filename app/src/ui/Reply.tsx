import type { ComponentChildren } from "preact";
import { ADVICE_LINE, NOT_COVERED, POISON_HELP, STANDING_LINE } from "../lib/router.ts";
import { labelDate, dailyMedUrl } from "../lib/openfda.ts";
import { notMentioned, type Quote } from "../lib/answer.ts";
import { noneMention, type BackupOutcome } from "../lib/backup.ts";
import { shortName } from "../lib/schedule.ts";
import type { Med } from "../lib/types.ts";
import type { Reply } from "../store.ts";

const tel = (n: string) => `tel:${n.replace(/[^0-9]/g, "")}`;

/** Turns phone numbers in fixed safety text into tap-to-call links. */
export function Callable({ text }: { text: string }) {
  const parts = text.split(/(1-800-222-1222|\b911\b|\b988\b)/);
  return <>{parts.map((p, i) => (i % 2 ? <a class="call" href={tel(p)}>{p}</a> : p))}</>;
}

function Box({ tone, children }: { tone: "alert" | "note" | "info"; children: ComponentChildren }) {
  return <div class={`box ${tone}`}>{children}</div>;
}

export function PharmacistPrompt() {
  return <p class="pharmacist">💬 Your pharmacist can answer this. You can call or visit them for free.</p>;
}

export function ReplyView({ reply, onChoose }: { reply: Reply; onChoose?: (m: Med) => void }) {
  switch (reply.kind) {
    case "emergency":
      return (
        <Box tone="alert">
          <p class="lead"><Callable text={reply.text} /></p>
          <div class="row">
            <a class="btn danger" href={tel(POISON_HELP)}>Call Poison Help</a>
            <a class="btn danger" href="tel:911">Call 911</a>
          </div>
        </Box>
      );
    case "schedule":
      return <Box tone="info"><p class="lead">{reply.text}</p><p class="small">From the times you set, not from the label.</p></Box>;
    case "info":
      return <Box tone="info"><p class="lead">{reply.text}</p>{reply.pharmacist && <PharmacistPrompt />}</Box>;
    case "choose":
      return (
        <Box tone="info">
          <p class="lead">Which medicine is this about?</p>
          <div class="chips">
            {reply.meds.map((m) => <button class="chip" onClick={() => onChoose?.(m)}>{shortName(m)}</button>)}
          </div>
        </Box>
      );
    case "label":
      return <LabelAnswer reply={reply} />;
  }
}

function Quotes({ quotes, caption }: { quotes: Quote[]; caption: ComponentChildren }) {
  return (
    <figure class="quotes">
      {quotes.map((q) => (
        <blockquote>
          {q.before && <span class="lead-in">{q.before} </span>}
          <mark>{q.text}</mark>
          <cite>{q.url ? <a href={q.url} target="_blank" rel="noopener">{q.section}</a> : q.section}</cite>
        </blockquote>
      ))}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

/** What the backup sources found, or an honest "none of them mention it". */
function BackupAnswer({ b }: { b: BackupOutcome }) {
  if (!b.hit) {
    return (
      <Box tone="note">
        <p class="lead">{noneMention(b.topic)}</p>
        <p class="small">We checked: your label, {b.checked.join(", ")}.</p>
        <PharmacistPrompt />
        <p>Read about this medicine: <a href={b.medline.url} target="_blank" rel="noopener">{b.medline.title}</a> (opens MedlinePlus)</p>
      </Box>
    );
  }
  const { source, result } = b.hit;
  const s = result.shown;
  return (
    <div class="backup">
      <p class="badge">{source.badge}</p>
      {s.kind === "answer" && <p class="plain">{s.restatement}</p>}
      {s.kind === "quotes" && <p class="plain">Here is what it says:</p>}
      {s.kind === "passages" && <p class="plain-sub">What it says about this (please read it yourself):</p>}
      {"quotes" in s && s.quotes.length > 0 && (
        <Quotes quotes={s.quotes} caption={<>
          <a href={source.url} target="_blank" rel="noopener">Open the source</a>
          {source.credit && <> · <a href={source.credit.url} target="_blank" rel="noopener">{source.credit.text}</a></>}
        </>} />
      )}
      <PharmacistPrompt />
      <p class="small">More about this medicine: <a href={b.medline.url} target="_blank" rel="noopener">{b.medline.title}</a></p>
    </div>
  );
}

function LabelAnswer({ reply }: { reply: Extract<Reply, { kind: "label" }> }) {
  const { result, advice, med, backup } = reply;
  const s = result.shown;
  const meta = result.label;
  const ask = backup ? null : <PharmacistPrompt />;
  return (
    <div class="answer">
      {advice && <Box tone="note"><p>{ADVICE_LINE}</p></Box>}
      {s.kind === "not-found" && (
        <Box tone="note"><p class="lead">{notMentioned(s.missing, result.near)}</p>{ask}</Box>
      )}
      {result.missing && s.kind !== "not-found" && s.kind !== "decline" && <p class="missing">{notMentioned(result.missing, result.near)}</p>}
      {s.kind === "answer" && <p class="plain">{s.restatement}</p>}
      {s.kind === "quotes" && <p class="plain">Here is what the label says:</p>}
      {s.kind === "decline" && (
        <Box tone="note"><p class="lead">{NOT_COVERED}</p>{ask}</Box>
      )}
      {s.kind === "passages" && (s.quotes.length ? (
        <p class={s.why === "declined" ? "plain" : "plain-sub"}>
          {s.why === "no-model" ? "What the label says about this (please read it yourself):"
            : s.why === "declined" ? "Your label says:"
            : "The answer couldn't be checked. What the label says about this:"}
        </p>
      ) : (
        <Box tone="note"><p class="lead">{NOT_COVERED}</p>{ask}</Box>
      ))}
      {"quotes" in s && s.quotes.length > 0 && (
        <Quotes quotes={s.quotes} caption={<>
          From the {meta.title} label ({shortName(med)}), {meta.manufacturer}, dated {labelDate(meta.effective)}.{" "}
          <a href={dailyMedUrl(meta.setId)} target="_blank" rel="noopener">Full label</a>
        </>} />
      )}
      {s.kind === "passages" && s.quotes.length > 0 && <PharmacistPrompt />}
      {backup && <BackupAnswer b={backup} />}
      <p class="standing">{STANDING_LINE}</p>
      {result.raw !== undefined && (
        <details class="small">
          <summary>How this answer was made</summary>
          <p>Model {result.modelKey} read the label sentences and its reply was checked: the quotes are copied from the label by the app, and every number, unit and drug name in the plain answer must appear in them. Took {(result.ms / 1000).toFixed(1)} s.</p>
          <pre>{result.raw}</pre>
        </details>
      )}
    </div>
  );
}
