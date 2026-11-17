// Calendar file export (plan §3 item 9): titles say "Medication time" unless the user opts in.
import type { Med } from "./types.ts";
import { shortName } from "./schedule.ts";

const pad = (n: number) => String(n).padStart(2, "0");
const stamp = (d: Date) =>
  `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");

/** Fold to 75 octets per RFC 5545. */
function fold(line: string): string {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return line;
  const out: string[] = [];
  let cur = "", len = 0;
  for (const ch of line) {
    const n = new TextEncoder().encode(ch).length;
    if (len + n > (out.length ? 74 : 75)) { out.push(cur); cur = ""; len = 0; }
    cur += ch;
    len += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

export function buildIcs(meds: Med[], opts: { includeNames: boolean; now: Date }): string {
  const { now } = opts;
  const day = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MedLabel//WAICY 2026//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  // One event per time; with names off, medicines at the same time share one event.
  const byTime = new Map<string, Med[]>();
  for (const m of meds) for (const t of m.times) byTime.set(t, [...(byTime.get(t) || []), m]);
  for (const [time, ms] of [...byTime].sort()) {
    const [h, mi] = time.split(":");
    const title = opts.includeNames ? `Medication time: ${ms.map(shortName).join(", ")}` : "Medication time";
    lines.push(
      "BEGIN:VEVENT",
      `UID:medlabel-${time.replace(":", "")}@medlabel.local`,
      `DTSTAMP:${stamp(now)}`,
      `DTSTART:${day}T${h}${mi}00`,
      "DURATION:PT15M",
      "RRULE:FREQ=DAILY",
      `SUMMARY:${esc(title)}`,
      "BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${esc(title)}`, "TRIGGER:PT0M", "END:VALARM",
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}
