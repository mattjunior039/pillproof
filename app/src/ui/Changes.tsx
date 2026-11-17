import { useEffect, useState } from "preact/hooks";
import { historyKeys, isoDate, type ChangesFile, type DrugHistory, type Update } from "../lib/changes.ts";
import { shortName } from "../lib/schedule.ts";
import type { Med } from "../lib/types.ts";
import { useApp } from "../store.ts";

let cache: ChangesFile | null = null;
let loading: Promise<ChangesFile> | null = null;

export function useChanges(): ChangesFile | null {
  const [d, setD] = useState(cache);
  useEffect(() => {
    if (cache) return;
    loading ??= import("../../data/label_changes.json").then((m) => (cache = m.default as unknown as ChangesFile));
    loading.then(setD);
  }, []);
  return d;
}

const KIND: Record<string, string> = {
  added: "Added", removed: "Removed", altered: "Changed", section_added: "New section", section_removed: "Section removed",
};

const NOTE = "Ask your pharmacist or doctor before changing anything.";

function Long({ text }: { text: string }) {
  if (text.length < 400) return <>{text}</>;
  return <details><summary>{text.slice(0, 220)}…</summary>{text}</details>;
}

function UpdateView({ u }: { u: Update }) {
  const counts = Object.entries(u.by_section || {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
  return (
    <li class="update">
      <h4>{isoDate(u.date)} <span class="sub">version {u.from_version} → {u.to_version}</span></h4>
      {u.kind === "format_rewrite" ? <p>{u.text}</p> : (
        <>
          <p class="small">{u.n_changes} change{u.n_changes === 1 ? "" : "s"} that may change meaning{counts ? ` (${counts})` : ""}.
            {u.n_listed !== undefined && u.n_listed < (u.n_changes ?? 0) ? ` Showing ${u.n_listed}.` : ""}</p>
          {u.changes?.length ? (
            <ul class="diffs">
              {u.changes.map((c) => (
                <li class={`diff ${c.kind}`}>
                  <p class="tag"><span class={`kind ${c.kind}`}>{KIND[c.kind]}</span> {c.section}</p>
                  <div class="pair">
                    <div class="old"><p class="small">Before</p><p>{c.old ? <del><Long text={c.old} /></del> : <em>(not in the label)</em>}</p></div>
                    <div class="new"><p class="small">After</p><p>{c.new ? <ins><Long text={c.new} /></ins> : <em>(taken out of the label)</em>}</p></div>
                  </div>
                  {c.plain_language && <p class="plain-sub">{c.plain_language}</p>}
                </li>
              ))}
            </ul>
          ) : u.n_changes ? <p class="small">Older update: only the count is kept here. The full text is on DailyMed.</p> : null}
        </>
      )}
    </li>
  );
}

function DrugView({ k, h, meds }: { k: string; h: DrugHistory; meds: Med[] }) {
  const mine = meds.filter((m) => historyKeys(m, { drugs: { [k]: h } } as ChangesFile).length);
  const otherMaker = mine.find((m) => m.label && m.label.manufacturer.toLowerCase() !== h.manufacturer.toLowerCase());
  return (
    <article class="card">
      <h2>{h.brand ? `${h.brand} (${k})` : k}</h2>
      {mine.length > 0 && <p class="sub">On your list: {mine.map(shortName).join(", ")}</p>}
      <p>
        History of the label from <strong>{h.manufacturer}</strong>, from {isoDate(h.history_from.date)} (version {h.history_from.version}) to{" "}
        {isoDate(h.latest.date)} (version {h.latest.version}): {h.n_versions} versions on DailyMed.
        {" "}<a href={`https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${h.set_id}`} target="_blank" rel="noopener">DailyMed</a>
      </p>
      {otherMaker && <p class="small">Your saved label is from {otherMaker.label!.manufacturer}. Labels from different makers usually change together, but check yours too.</p>}
      <p class="box note">{NOTE}</p>
      {h.updates.length ? <ul class="updates">{h.updates.map((u) => <UpdateView u={u} />)}</ul> : <p>No safety-section changes found in this history.</p>}
    </article>
  );
}

export function Changes() {
  const s = useApp();
  const data = useChanges();
  const [all, setAll] = useState(false);
  if (!data) return <section><h1>Label changes</h1><p class="busy">Loading…</p></section>;
  const mine = [...new Set(s.meds.flatMap((m) => historyKeys(m, data)))];
  const keys = all ? Object.keys(data.drugs) : mine;
  return (
    <section>
      <h1>Label changes</h1>
      <p>What changed in the safety sections of a label between versions: warnings, interactions, who shouldn't take it, and the patient information. Old sentence on the left, new on the right.</p>
      <p class="box note"><strong>{NOTE}</strong> A label change doesn't mean your medicine is unsafe.</p>
      {!mine.length && !all && <p>None of your medicines are among the {Object.keys(data.drugs).length} labels tracked so far.</p>}
      <label class="check"><input type="checkbox" checked={all} onChange={(e) => setAll((e.target as HTMLInputElement).checked)} /> Show all {Object.keys(data.drugs).length} tracked labels</label>
      {keys.map((k) => <DrugView k={k} h={data.drugs[k]} meds={s.meds} />)}
      <p class="small">Changes found by comparing DailyMed label versions sentence by sentence (built {isoDate(data.generated)}). Changes that an automatic check judged to be only rewording are left out, so a few small changes may be missing. {data.listing}.</p>
    </section>
  );
}
