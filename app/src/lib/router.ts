// Question router (plan §5 step 2): emergency, schedule, label question or out of scope.
// Simple rules; emergency words never reach the model (plan §3 item 7).
import type { Med } from "./types.ts";
import { lexiconMentions, medNames, medsMentioned, words } from "./names.ts";

export const POISON_HELP = "1-800-222-1222";

export const EMERGENCY_TEXT =
  "If someone took too much, swallowed something by mistake, or is having a bad reaction, get help now. " +
  `Call Poison Help at ${POISON_HELP} (free, 24 hours). ` +
  "If the person has collapsed, has a seizure, has trouble breathing, or can't be woken up, call 911.";

export const CRISIS_TEXT =
  "If you are thinking about hurting yourself, call or text 988 (Suicide and Crisis Lifeline) to talk to someone now. " +
  `If someone took too much of a medicine, call Poison Help at ${POISON_HELP}. In an emergency, call 911.`;

export const ADVICE_LINE =
  "I can only show what the label says. Whether to take, skip, stop or change a dose is a decision for you and your pharmacist or doctor.";

export const STANDING_LINE = "This is information from the FDA label, not medical advice for you.";

const EMERGENCY = [
  /\bover ?dos(e|ed|ing)\b/, /\b(took|taken|take|swallowed|ate|had) (way )?too (much|many)\b/,
  /\btoo (many|much) (pills?|tablets?|capsules?|doses?)\b/,
  /\b(accidentally|by accident|by mistake)\b.*\b(took|taken|swallowed|ate|gave|double)/,
  /\b(took|taken|swallowed|ate|gave)\b.*\b(accidentally|by accident|by mistake)\b/,
  /\b(child|kid|baby|toddler|dog|cat)\b.*\b(swallowed|ate|took|got into)\b/,
  /\bpoison(ed|ing)?\b/,
  /\b(can'?t|cannot|can not|hard to|trouble|difficulty|not) breath(e|ing)\b/, /\bshort of breath\b/,
  /\bchest pain\b/, /\b(unconscious|unresponsive|passed out|fainted|not waking|won'?t wake|seizure|seizing|convuls)/,
  /\b(throat|tongue|lips?|face) (is |are )?(closing|swelling|swollen)\b/, /\banaphyla/,
];
const CRISIS = [/\bsuicid/, /\bkill (my|him|her)self\b/, /\bend (my|it all|my life)\b/, /\b(hurt|harm) (my|him|her)self\b/, /\bwant to die\b/];

const SCHEDULE = [
  /\bwhat('?s| is) next\b/, /\bnext (dose|pill|medicine|medication|med)s?\b/, /\bwhen('?s| is) my next\b/,
  /\bwhen do i (take|have)\b/, /\bwhat time do i\b/, /\bwhat do i take\b/, /\bis it time\b/,
  /\bmy (schedule|times|dose times)\b/, /\b(today'?s|tonight'?s) (medicines|meds|medications|pills|doses|schedule)\b/,
  /\bwhat (medicines|meds|medications|pills) (do i|are)\b.*\b(today|tonight|now|morning|evening|left)\b/,
];

// Questions about the user's own decisions get the advice line before the label text.
const ADVICE = [
  /\bshould i (stop|quit|skip|double|change|increase|decrease|lower|raise|cut|split|keep taking|start|take more|take less)\b/,
  /\bcan i (stop|quit|skip|double)\b/, /\b(is it|it'?s) (ok|okay|safe|fine) (for me )?to (stop|skip|double|quit)\b/,
];

const MED_WORDS = /\b(take|taking|took|dose|doses|dosage|dosing|pill|pills|tablets?|capsules?|mg|side effects?|food|meals?|empty stomach|eat|drink|alcohol|grapefruit|juice|pregnan\w*|breast ?feed\w*|nursing|missed|miss|store|storage|stored|fridge|refrigerat\w*|interact\w*|warnings?|allerg\w*|kidneys?|liver|heart|blood|pressure|sugar|used for|it for|it do|does it|how long|how much|how often|children|child|kids?|older|elderly|stomach|dizz\w*|sleepy|drowsy|drive|driving|label|ingredients?|crush|chew|split|swallow|bleed\w*|muscles?|rash|swelling|weight|medicines?|medications?|meds|drugs?|prescri\w*|generic|brand|overdose|symptoms?|pain|headache|nausea|vomit\w*|diarrh\w*|constipat\w*|tired|fatigue|anything else|avoid|stop|stopping|quit|skip|double)\b/;

export type Route =
  | { kind: "emergency"; text: string }
  | { kind: "schedule" }
  | { kind: "label"; med: Med; advice: boolean }
  | { kind: "choose"; meds: Med[]; advice: boolean }
  | { kind: "not-on-list"; names: string[] }
  | { kind: "no-meds" }
  | { kind: "out-of-scope" };

export function route(question: string, meds: Med[], lexicon: Set<string>, lastMed?: Med | null): Route {
  const q = question.toLowerCase().replace(/[’‘]/g, "'");
  if (CRISIS.some((r) => r.test(q))) return { kind: "emergency", text: CRISIS_TEXT };
  if (EMERGENCY.some((r) => r.test(q))) return { kind: "emergency", text: EMERGENCY_TEXT };
  if (SCHEDULE.some((r) => r.test(q))) return { kind: "schedule" };
  const advice = ADVICE.some((r) => r.test(q));
  const named = medsMentioned(q, meds);
  if (named.length === 1) return { kind: "label", med: named[0], advice };
  if (named.length > 1) return { kind: "choose", meds: named, advice };
  const known = new Set(meds.flatMap(medNames).flatMap((n) => n.split(" ")));
  const others = lexiconMentions(q, lexicon).filter((w) => !known.has(w));
  if (others.length) return { kind: "not-on-list", names: others };
  if (!MED_WORDS.test(q) && words(q).length > 0) return { kind: "out-of-scope" };
  if (!meds.length) return { kind: "no-meds" };
  if (meds.length === 1) return { kind: "label", med: meds[0], advice };
  if (lastMed && meds.some((m) => m.id === lastMed.id) && /\b(it|this|that|them|these)\b/.test(q)) {
    return { kind: "label", med: lastMed, advice };
  }
  return { kind: "choose", meds, advice };
}

export const NOT_COVERED =
  "The label does not cover this. That does not mean it is safe or unsafe. Please ask your pharmacist; they can answer questions the label doesn't.";
