import { allowedModels, SIZE_MB, type ModelEntry } from "../lib/device.ts";
import { POISON_HELP } from "../lib/router.ts";
import {
  chooseModel, currentModel, downloadModel, loadModel, removeModels, resetCrash, saveSettings, useApp, vectorize,
} from "../store.ts";
import { downloadIcs } from "./Today.tsx";
import { ModelBanner } from "./Ask.tsx";

/** Dev-set numbers from app/models.json, shown as given (the Gate 2 session owns their meaning). */
function devLine(m: ModelEntry, tier: "desktop" | "phone"): string {
  const all = (m.dev || {}) as Record<string, any>;
  // models.json nests metrics by prompt set (phone / desktop / oracle); show the one this device uses.
  const set = all[tier] && typeof all[tier] === "object" ? tier : all.phone && typeof all.phone === "object" ? "phone" : null;
  const dev = set ? all[set] : all;
  const pick = ["wrong_rate", "overall_correct", "false_decline_rate", "false_answer_rate"];
  const bits = Object.entries(dev)
    .filter(([k]) => !set || pick.includes(k))
    .filter(([, v]) => typeof v === "number")
    .map(([k, v]) => `${k.replace(/_/g, " ")} ${set ? `${v}%` : v}`);
  return bits.length ? `Development set${set ? ` (${set} prompts, with checks)` : ""}: ${bits.join(", ")}` : "";
}

export function Settings() {
  const s = useApp();
  const st = s.settings;
  const models = allowedModels(s.tier);
  const cur = currentModel();
  const m = s.model;
  const canRun = s.gpu?.ok && !s.crash;
  return (
    <section>
      <h1>Settings</h1>

      <h2>Reading</h2>
      <fieldset class="seg">
        <legend>Text size</legend>
        {(["Large", "Larger", "Largest"] as const).map((n, i) => (
          <label><input type="radio" name="text" checked={st.text === i} onChange={() => saveSettings({ text: i as 0 | 1 | 2 })} /> {n}</label>
        ))}
      </fieldset>
      <label class="check"><input type="checkbox" checked={st.contrast} onChange={(e) => saveSettings({ contrast: (e.target as HTMLInputElement).checked })} /> High contrast</label>
      <label class="check"><input type="checkbox" checked={st.speakAnswers} onChange={(e) => saveSettings({ speakAnswers: (e.target as HTMLInputElement).checked })} /> Read answers aloud on the Voice screen</label>

      <h2>Answers</h2>
      <ModelBanner inSettings />
      <fieldset class="seg">
        <legend>How answers are made</legend>
        <label><input type="radio" name="mode" checked={st.answerMode === "model"} onChange={() => saveSettings({ answerMode: "model" })} disabled={!canRun} />
          Short plain answer, checked against the label, with the quotes</label>
        <label><input type="radio" name="mode" checked={st.answerMode === "passages"} onChange={() => saveSettings({ answerMode: "passages" })} />
          Label sentences only (no model; works on any device)</label>
      </fieldset>
      {canRun && st.answerMode === "model" && (
        <div class="card">
          <label for="model">Answer model</label>
          <select id="model" value={cur.key} onChange={(e) => chooseModel((e.target as HTMLSelectElement).value)} disabled={m.status === "loading"}>
            {models.map((x) => (
              <option value={x.key}>{x.key} ({x.size}, {SIZE_MB[x.size]} MB){m.cached[x.key] ? ", downloaded" : ""}</option>
            ))}
          </select>
          {devLine(cur, s.tier) && <p class="small">{devLine(cur, s.tier)}</p>}
          {s.tier === "phone" && <p class="small">Phones use the smaller 0.8B model; the 2B model runs out of memory on phones.</p>}
          <div class="row">
            {m.status !== "ready" && m.status !== "loading" && (
              st.modelConsent || m.cached[cur.key]
                ? <button class="btn primary" onClick={() => loadModel().catch(() => {})}>Load model</button>
                : <button class="btn primary" onClick={() => downloadModel().catch(() => {})}>Download model ({SIZE_MB[cur.size]} MB, once)</button>
            )}
            {m.status === "ready" && <p class="ok">✓ {cur.key} is ready on this device.</p>}
            <button class="btn danger-outline" onClick={() => { if (confirm("Delete the downloaded answer models from this device?")) removeModels(); }}>Delete downloaded models</button>
          </div>
          <p class="small">The model runs inside this browser. Your questions never leave the device.</p>
        </div>
      )}
      {s.crash && (
        <div class="card">
          <p>{s.crash}</p>
          <button class="btn" onClick={resetCrash}>Try the model again</button>
        </div>
      )}
      <label class="check">
        <input type="checkbox" checked={st.smartSearch} onChange={(e) => {
          const on = (e.target as HTMLInputElement).checked;
          saveSettings({ smartSearch: on });
          if (on) for (const med of s.meds) if (med.label) vectorize(med.label.splId);
        }} />
        Smarter label search (finds sentences that use different words; downloads 34 MB once)
      </label>
      <label class="check">
        <input type="checkbox" checked={st.backupSources} onChange={(e) => saveSettings({ backupSources: (e.target as HTMLInputElement).checked })} />
        When my label doesn't answer, check other trusted sources: other FDA labels for the same medicine, FDA consumer pages on food and drink, and the DDInter drug–food database. Answers from them are marked.
      </label>
      {Object.keys(s.vectors).length > 0 && <p class="small">Preparing label search… {Object.values(s.vectors).join(", ")}</p>}

      <h2>Calendar</h2>
      <label class="check"><input type="checkbox" checked={st.calendarNames} onChange={(e) => saveSettings({ calendarNames: (e.target as HTMLInputElement).checked })} /> Show medicine names in calendar events</label>
      <button class="btn" disabled={!s.meds.length} onClick={() => downloadIcs(s.meds, st.calendarNames)}>Download calendar file (.ics)</button>

      <h2>About</h2>
      <p>MedLabel answers questions from the FDA label of each medicine on your list. It is reference information, not medical advice. It never tells you to change a dose or stop a medicine.</p>
      <p>Emergency: Poison Help <a href={`tel:${POISON_HELP.replace(/-/g, "")}`}>{POISON_HELP}</a> (24 hours, free), or call <a href="tel:911">911</a>.</p>
      <p class="small">Everything stays in this browser: no accounts, no server, no analytics. Labels come from openFDA, names from RxNorm, label history from DailyMed.</p>
    </section>
  );
}
