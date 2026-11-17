import { useEffect, useRef, useState } from "preact/hooks";
import { dailyMedUrl, labelDate, manufacturers } from "../lib/openfda.ts";
import { contents, displayNames, isCombo, products, suggest, type Product } from "../lib/rxnorm.ts";
import { formatTime, shortName } from "../lib/schedule.ts";
import type { Med } from "../lib/types.ts";
import { addMed, deleteMed, fetchLabel, labelLoading, updateMed, useApp } from "../store.ts";

const PRESETS: [string, string][] = [["Morning", "08:00"], ["Noon", "12:00"], ["Evening", "18:00"], ["Bedtime", "21:00"]];

function TimesEditor({ times, onChange }: { times: string[]; onChange: (t: string[]) => void }) {
  const sorted = (t: string[]) => [...new Set(t)].sort();
  return (
    <fieldset class="times">
      <legend>Dose times you were told to use</legend>
      {times.map((t, i) => (
        <div class="row">
          <input type="time" value={t} aria-label={`Time ${i + 1}`} onChange={(e) => onChange(sorted(times.map((x, j) => (j === i ? (e.target as HTMLInputElement).value : x)).filter(Boolean)))} />
          <button class="btn" onClick={() => onChange(times.filter((_, j) => j !== i))} aria-label={`Remove ${formatTime(t)}`}>Remove</button>
        </div>
      ))}
      <div class="chips">
        {PRESETS.filter(([, v]) => !times.includes(v)).map(([n, v]) => (
          <button class="chip" onClick={() => onChange(sorted([...times, v]))}>+ {n} ({formatTime(v)})</button>
        ))}
        <button class="chip" onClick={() => onChange(sorted([...times, "09:00"]))}>+ Other time</button>
      </div>
    </fieldset>
  );
}

function AddMed({ onDone }: { onDone: () => void }) {
  const [q, setQ] = useState("");
  const [names, setNames] = useState<string[] | null>(null);
  const [err, setErr] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [prods, setProds] = useState<Product[] | null>(null);
  const [prod, setProd] = useState<Product | null>(null);
  const [showCombos, setShowCombos] = useState(false);
  const [times, setTimes] = useState<string[]>(["08:00"]);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    displayNames().then(setNames).catch(() => setErr("Can't reach RxNorm to look up names. Check your connection."));
  }, []);

  const pick = async (name: string) => {
    setPicked(name);
    setProds(null);
    setErr("");
    try {
      const p = await products(name);
      setProds(p);
      if (!p.length) setErr("RxNorm has no tablets, capsules or liquids under that name. Try the generic name.");
    } catch (e) {
      setErr(String((e as Error).message));
    }
  };

  if (prod) {
    const parts = contents(prod);
    return (
      <div class="card">
        <h2>{prod.brand || (prod.combo ? "Combination product" : prod.ingredient)}</h2>
        <p class="contains-head">{parts.length > 1 ? `Contains ${parts.length} active ingredients:` : "Active ingredient:"}</p>
        <ul class="contains">{parts.map((c) => <li>{c}</li>)}</ul>
        <p>Form: {prod.form.toLowerCase()}</p>
        <p class={prod.combo ? "notice" : "small"}>
          Check this matches the active ingredients on your bottle, box or Drug Facts panel.
          {prod.combo ? " This is a combination product; if your medicine has only one ingredient, go back and choose again." : ""}
        </p>
        <TimesEditor times={times} onChange={setTimes} />
        <div class="row">
          <button class="btn primary" onClick={async () => {
            await addMed({ rxcui: prod.rxcui, name: prod.name, ingredient: prod.ingredient, strength: prod.strength, form: prod.form, brand: prod.brand, times });
            onDone();
            scrollTo(0, 0);
          }}>Save</button>
          <button class="btn" onClick={() => setProd(null)}>Back</button>
        </div>
        <p class="small">Saving downloads this medicine's FDA label so you can ask about it offline.</p>
      </div>
    );
  }

  if (picked) {
    const singles = prods?.filter((p) => !p.combo) ?? [];
    const combos = prods?.filter((p) => p.combo) ?? [];
    const shown = singles.length && !showCombos ? singles : [...singles, ...combos];
    return (
      <div class="card">
        <h2>Which {picked.replace(/ \/ /g, " + ")}?</h2>
        <p>Pick the strength and form on your bottle or box.</p>
        {err && <p class="error">{err}</p>}
        {!prods && !err && <p class="busy">Looking up products…</p>}
        <ul class="picklist">
          {shown.map((p) => (
            <li><button class="pick" onClick={() => setProd(p)}>
              {p.combo ? <><strong>Combination:</strong> {contents(p).join(" + ")}</> : <><strong>{p.strength.toLowerCase() || "—"}</strong> {p.ingredient}</>}
              <span class="sub">{p.form}{p.brand ? ` · Brand: ${p.brand}` : " · Generic"}</span>
            </button></li>
          ))}
        </ul>
        {singles.length > 0 && combos.length > 0 && !showCombos && (
          <button class="btn" onClick={() => setShowCombos(true)}>Show {combos.length} combination products (more than one ingredient)</button>
        )}
        <button class="btn" onClick={() => { setPicked(null); setProds(null); setErr(""); setShowCombos(false); }}>Back</button>
      </div>
    );
  }

  const list = names ? suggest(names, q) : [];
  return (
    <div class="card">
      <h2>Add a medicine</h2>
      <label for="med-search">Name on the label (brand or generic)</label>
      <input id="med-search" ref={input} type="search" autocomplete="off" value={q} placeholder="e.g. Lipitor or atorvastatin"
        aria-controls="med-suggest"
        onInput={(e) => setQ((e.target as HTMLInputElement).value)}
        onKeyDown={(e) => { if (e.key === "Enter" && list[0]) pick(list[0]); }} />
      {err && <p class="error">{err}</p>}
      {!names && !err && <p class="busy">Loading medicine names…</p>}
      <ul id="med-suggest" class="picklist" role="listbox">
        {list.map((n) => (
          <li role="option"><button class="pick" onClick={() => pick(n)}>
            {isCombo(n) ? <>{n.replace(/ \/ /g, " + ")} <span class="tag">combination</span></> : n}
          </button></li>
        ))}
      </ul>
      <button class="btn" onClick={onDone}>Cancel</button>
    </div>
  );
}

function LabelInfo({ med }: { med: Med }) {
  const [mfs, setMfs] = useState<string[] | null>(null);
  const [open, setOpen] = useState(false);
  const loading = labelLoading.has(med.id);
  if (loading) return <p class="busy">Getting the FDA label…</p>;
  if (!med.label) {
    return (
      <div>
        <p class="error">{med.labelError || "No label yet."}</p>
        <button class="btn" onClick={() => fetchLabel(med)}>Get label</button>
      </div>
    );
  }
  const l = med.label;
  return (
    <div class="labelinfo">
      <p>
        Label: <strong>{l.manufacturer}</strong>, dated {labelDate(l.effective)}
        {l.hasPatient ? "" : " (no patient section)"}.{" "}
        <a href={dailyMedUrl(l.setId)} target="_blank" rel="noopener">Read it on DailyMed</a>
      </p>
      {!open ? (
        <button class="btn" onClick={async () => { setOpen(true); setMfs(await manufacturers(med).catch(() => [])); }}>Different manufacturer?</button>
      ) : (
        <div>
          <label for={`mf-${med.id}`}>The maker printed on your bottle or box</label>
          {!mfs ? <p class="busy">Loading makers…</p> : (
            <select id={`mf-${med.id}`} onChange={(e) => { const v = (e.target as HTMLSelectElement).value; if (v) { setOpen(false); fetchLabel(med, v); } }}>
              <option value="">Choose…</option>
              {mfs.map((m) => <option value={m} selected={m === l.manufacturer}>{m}</option>)}
            </select>
          )}
          <button class="btn" onClick={() => setOpen(false)}>Cancel</button>
        </div>
      )}
    </div>
  );
}

function MedCard({ med }: { med: Med }) {
  const [editing, setEditing] = useState(false);
  const [times, setTimes] = useState(med.times);
  return (
    <li class="card">
      <h2>{shortName(med)}</h2>
      {(med.brand || med.ingredient.includes(" / ")) && <p class="sub">Contains: {contents(med).join(" + ")}</p>}
      {editing ? (
        <>
          <TimesEditor times={times} onChange={setTimes} />
          <div class="row">
            <button class="btn primary" onClick={async () => { await updateMed({ ...med, times }); setEditing(false); }}>Save times</button>
            <button class="btn" onClick={() => { setTimes(med.times); setEditing(false); }}>Cancel</button>
          </div>
        </>
      ) : (
        <p>{med.times.length ? med.times.map(formatTime).join(", ") : "No times set"}</p>
      )}
      <LabelInfo med={med} />
      {!editing && (
        <div class="row">
          <button class="btn" onClick={() => setEditing(true)}>Edit times</button>
          <button class="btn danger-outline" onClick={() => { if (confirm(`Remove ${shortName(med)} from your list?`)) deleteMed(med.id); }}>Remove</button>
        </div>
      )}
    </li>
  );
}

export function Meds() {
  const s = useApp();
  const [adding, setAdding] = useState(s.meds.length === 0);
  return (
    <section>
      <h1>Medicines</h1>
      {adding ? <AddMed onDone={() => setAdding(false)} /> : <button class="btn primary big" onClick={() => setAdding(true)}>+ Add a medicine</button>}
      <ul class="cards">{s.meds.map((m) => <MedCard key={m.id} med={m} />)}</ul>
      <p class="small">Names and products come from RxNorm (National Library of Medicine); labels come from openFDA. Your list stays on this device.</p>
    </section>
  );
}
