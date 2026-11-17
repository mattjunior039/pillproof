// Today timeline and schedule answers: plain code, never the model (plan §3 item 1).
import type { Med } from "./types.ts";
import { medsMentioned } from "./names.ts";

export interface Dose { time: string; minutes: number; med: Med; state: "past" | "next" | "later" }

export const toMinutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

export function formatTime(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const ap = h < 12 ? "AM" : "PM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ap}`;
}

/** Short spoken/display name, e.g. "atorvastatin 20 mg tablet". */
export function shortName(med: Med): string {
  const form = med.form.toLowerCase().replace(/^oral /, "");
  return [med.brand || med.ingredient, med.strength.replace(/ MG\b/g, " mg").replace(/ MCG\b/g, " mcg").replace(/ ML\b/g, " mL"), form]
    .filter(Boolean).join(" ");
}

export function todayDoses(meds: Med[], now: Date): Dose[] {
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const doses = meds.flatMap((med) => med.times.map((time) => ({ time, minutes: toMinutes(time), med, state: "later" as Dose["state"] })))
    .sort((a, b) => a.minutes - b.minutes || shortName(a.med).localeCompare(shortName(b.med)));
  let nextMin: number | null = null;
  for (const d of doses) {
    if (d.minutes < nowMin) d.state = "past";
    else if (nextMin === null || d.minutes === nextMin) { d.state = "next"; nextMin = d.minutes; }
  }
  return doses;
}

function inWords(mins: number): string {
  if (mins < 1) return "now";
  const h = Math.floor(mins / 60), m = mins % 60;
  const parts = [h ? `${h} hour${h > 1 ? "s" : ""}` : "", m ? `${m} minute${m > 1 ? "s" : ""}` : ""].filter(Boolean);
  return `in ${parts.join(" and ")}`;
}

const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** The next dose time (today, or the first one tomorrow) and the medicines due then. */
export function nextDoses(meds: Med[], now: Date): { time: string; meds: Med[]; tomorrow: boolean; minutesAway: number } | null {
  const all = todayDoses(meds, now);
  if (!all.length) return null;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const next = all.filter((d) => d.state === "next");
  const tomorrow = next.length === 0;
  const group = tomorrow ? all.filter((d) => d.minutes === all[0].minutes) : next;
  const minutesAway = group[0].minutes - nowMin + (tomorrow ? 24 * 60 : 0);
  return { time: group[0].time, meds: group.map((d) => d.med), tomorrow, minutesAway };
}

/** Answer a schedule question from the stored times. */
export function answerSchedule(question: string, meds: Med[], now: Date): string {
  if (!meds.length) return "You have no medicines on your list yet. Add one on the Medicines screen.";
  const named = medsMentioned(question, meds);
  const q = question.toLowerCase();
  if (named.length && !/\bnext\b/.test(q)) {
    return named.map((m) => {
      if (!m.times.length) return `You have not set times for ${shortName(m)}.`;
      return `You set ${shortName(m)} for ${list(m.times.map(formatTime))}.`;
    }).join(" ");
  }
  if (/\b(today|schedule|all|list|tonight|this (morning|afternoon|evening))\b/.test(q)) {
    const doses = todayDoses(meds, now);
    if (!doses.length) return "You have not set any dose times.";
    const byTime = new Map<string, string[]>();
    for (const d of doses) byTime.set(d.time, [...(byTime.get(d.time) || []), shortName(d.med)]);
    return "Today: " + [...byTime].map(([t, ns]) => `${formatTime(t)}, ${list(ns)}`).join(". ") + ".";
  }
  const pool = named.length ? named : meds;
  const nx = nextDoses(pool, now);
  if (!nx) return "You have not set any dose times.";
  const when = nx.tomorrow ? `tomorrow at ${formatTime(nx.time)}` : `at ${formatTime(nx.time)}, ${inWords(nx.minutesAway)}`;
  return `Next: ${list(nx.meds.map(shortName))} ${when}.`;
}
