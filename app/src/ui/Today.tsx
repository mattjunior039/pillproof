import { useEffect, useState } from "preact/hooks";
import { buildIcs } from "../lib/ics.ts";
import { formatTime, nextDoses, shortName, todayDoses } from "../lib/schedule.ts";
import { go, saveSettings, useApp } from "../store.ts";
import { useChanges } from "./Changes.tsx";
import { historyKeys, recentUpdates } from "../lib/changes.ts";

function useNow(ms = 30_000) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, []);
  return now;
}

export function downloadIcs(meds: Parameters<typeof buildIcs>[0], includeNames: boolean) {
  const blob = new Blob([buildIcs(meds, { includeNames, now: new Date() })], { type: "text/calendar" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "medication-times.ics";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export function Today() {
  const s = useApp();
  const now = useNow();
  const changes = useChanges();
  const doses = todayDoses(s.meds, now);
  const next = nextDoses(s.meds, now);
  const since = new Date(now.getTime() - 365 * 864e5).toISOString().slice(0, 10);
  const changed = changes ? s.meds.filter((m) => historyKeys(m, changes).some((k) => recentUpdates(changes.drugs[k], since).length)) : [];

  if (!s.meds.length) {
    return (
      <section>
        <h1>Today</h1>
        <p class="lead">No medicines yet.</p>
        <button class="btn primary big" onClick={() => go("meds")}>Add a medicine</button>
      </section>
    );
  }
  return (
    <section>
      <h1>Today</h1>
      <p class="date">{now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
      {next && (
        <div class="box next" aria-live="polite">
          <p class="small">Next</p>
          <p class="lead"><strong>{formatTime(next.time)}</strong>{next.tomorrow ? " tomorrow" : ""}</p>
          <p>{next.meds.map(shortName).join(", ")}</p>
        </div>
      )}
      {doses.length ? (
        <ol class="timeline">
          {doses.map((d) => (
            <li class={d.state}>
              <span class="time">{formatTime(d.time)}</span>
              <span class="what">{shortName(d.med)}</span>
              <span class="state">{d.state === "past" ? "Earlier" : d.state === "next" ? "Next" : ""}</span>
            </li>
          ))}
        </ol>
      ) : <p>You haven't set any dose times. Add them on the Medicines screen.</p>}
      <p class="small">Times are the ones you set. This app does not decide when to take anything.</p>
      {changed.length > 0 && (
        <button class="box note linkbox" onClick={() => go("changes")}>
          <strong>Label updates in the past year:</strong> {changed.map(shortName).join(", ")}. See what changed →
        </button>
      )}
      <div class="row">
        <button class="btn" onClick={() => downloadIcs(s.meds, s.settings.calendarNames)}>Add times to my calendar (.ics)</button>
      </div>
      <label class="check">
        <input type="checkbox" checked={s.settings.calendarNames} onChange={(e) => saveSettings({ calendarNames: (e.target as HTMLInputElement).checked })} />
        Show medicine names in calendar events (otherwise they say "Medication time")
      </label>
    </section>
  );
}
