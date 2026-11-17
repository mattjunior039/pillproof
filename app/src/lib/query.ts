// Everyday wording -> label wording. Two uses:
//  1. searchQuery: extra label-vocabulary words for keyword search (the model still sees the
//     user's own question). People ask about "side effects" and "pregnant"; labels say
//     "adverse reactions" and "pregnancy", which BM25 alone would miss.
//  2. concepts: what the question is about, so the app can tell when the label does not
//     mention it at all ("grapefruit juice") instead of showing sentences that only share
//     generic words like "take" or "drink".
import { contentTokens } from "../../../core/text.js";

interface Topic {
  q: RegExp;
  /** Label words added to the keyword search. */
  add: string;
  /** A label sentence (lowercased, with its heading) that mentions the topic. */
  hit: RegExp;
  /** How to name it in "the label does not mention …" (default: the user's words). */
  name?: string;
  /** Section headings that are about this topic; their sentences rank a little higher. */
  head?: RegExp;
}

const TOPICS: Topic[] = [
  { q: /\bside[- ]?effects?\b/, add: "side effects adverse reactions", hit: /side effect|adverse|reactions?\b/, name: "side effects", head: /side effects|adverse reactions/ },
  { q: /\bpregnan\w*|\bexpecting\b/, add: "pregnancy pregnant fetus", hit: /pregnan|fetus|fetal|unborn/, name: "pregnancy", head: /pregnan/ },
  { q: /\bbreast[- ]?(feed\w*|fed|milk)|\bnursing\b/, add: "breastfeeding breast milk lactation nursing", hit: /breast|lactat|nursing/, name: "breastfeeding", head: /breast|lactation/ },
  { q: /\b(miss|missed|missing|skip|skipped|forget|forgot|forgotten)\b/, add: "miss missed dose", hit: /\bmiss|\bforget|\bskip/, name: "a missed dose", head: /how should i (take|use)|missed/ },
  { q: /\b(food|meals?|eat|eating|empty stomach|breakfast|lunch|dinner|supper)\b/, add: "food meals", hit: /\bfood|\bmeal|empty stomach|\beat/, name: "food", head: /how should i (take|use)|dosage/ },
  { q: /\b(alcohol\w*|beer|wine|liquor|drunk)\b/, add: "alcohol alcoholic drinks", hit: /(?<!(?:soluble|miscible) in |(?:benzyl|cetyl|stearyl|cetostearyl|polyvinyl|isopropyl|dehydrated|ethyl|lauryl|oleyl|myristyl) )alcohol(?! ?\(?(?:usp|nf)\b)|\bbeer\b|\bwine\b|liquor/, name: "alcohol", head: /avoid/ },
  { q: /\b(coffee|caffeine|energy drinks?|soda|cola)\b/, add: "caffeine coffee", hit: /caffeine|coffee/ },
  { q: /\b(store|storage|stored|fridge|refrigerat\w*|temperature)\b/, add: "store storage temperature", hit: /\bstor|temperature|refrigerat|°/, name: "storage", head: /stor/ },
  { q: /\b(overdose\w*|too (much|many)|extra (dose|pill|tablet)s?|double (dose|up)|took two)\b/, add: "overdose overdosage too much", hit: /overdos|too much|more than (directed|prescribed)/, name: "taking too much", head: /overdos|how should i (take|use)/ },
  { q: /\b(kids?|child|children|teen\w*|toddler\w*|bab(y|ies)|infants?|my (son|daughter))\b/, add: "children pediatric", hit: /(?<!(?:reach of|unborn) )child|pediatric|teen|years of age|infant/, name: "children", head: /pediatric|in children/ },
  { q: /\b(elderly|older|seniors?)\b/, add: "elderly older geriatric", hit: /elderly|older|geriatric/, name: "older adults", head: /geriatric/ },
  { q: /\b(interact\w*|together|mix\w*|combin\w*|other (medicines|medications|drugs|meds|pills))\b/, add: "interactions other medicines", hit: /interact|other (medicines|drugs|medications)|taking/, name: "other medicines", head: /interaction|tell my healthcare provider/ },
  { q: /\b(what is it for|used for|what does it do|treats?|why (am i|do i) take)\b/, add: "prescription medicine used to treat indicated treatment indications uses", hit: /\bused (to|for|in)\b|\bindicated (for|as|in)\b|\bto treat\b|treatment of|\buses\b|relieves/, name: "what it is used for", head: /^what (is|are) |indications|^uses/ },
  { q: /\b(how much|how many|dosage|how often)\b/, add: "dose dosage", hit: /\bdos|\btake \d|\bmg\b/, name: "the dose", head: /how should i (take|use)|dosage|directions/ },
  { q: /\b(night|morning|bedtime|evening|time of day)\b/, add: "time of day morning evening bedtime", hit: /time of day|morning|evening|bedtime|night|same time/ },
  { q: /\b(ibuprofen|advil|motrin|naproxen|aleve|aspirin|nsaids?|painkillers?|pain relievers?)\b/, add: "nsaids nonsteroidal anti-inflammatory", hit: /nsaid|anti-inflammatory|ibuprofen|naproxen|aspirin|pain reliever/ },
  { q: /\b(tylenol|acetaminophen|paracetamol)\b/, add: "acetaminophen", hit: /acetaminophen/ },
  { q: /\b(drive|driving|sleepy|drowsy|dizzy|dizziness)\b/, add: "drowsiness dizziness driving machinery", hit: /driv|machine|drows|dizz|sleep/ },
  { q: /\b(tired|tiredness|fatigue\w*|exhausted|weak|weakness)\b/, add: "tiredness fatigue weakness", hit: /tired|fatigue|weak|asthenia/ },
  { q: /\b(sleep\w*|insomnia)\b/, add: "sleep insomnia", hit: /sleep|insomnia/ },
  { q: /\b(throw(ing)? up|vomit\w*|puk\w*|nause\w*)\b/, add: "nausea vomiting", hit: /vomit|nausea/ },
  { q: /\ballerg\w*/, add: "allergic reaction hypersensitivity", hit: /allerg|hypersensitiv|hives/, name: "allergies" },
  { q: /\bkidneys?\b/, add: "kidney renal", hit: /kidney|renal/, name: "kidneys" },
  { q: /\bliver\b/, add: "liver hepatic", hit: /liver|hepat/, name: "the liver" },
  { q: /\b(stop|stopping|quit)\b/, add: "stop taking discontinue", hit: /\bstop|discontinu/, name: "stopping" },
  { q: /\b(crush\w*|chew\w*|split\w*|cut|break|swallow\w*)\b/, add: "crush chew split break swallow whole", hit: /crush|chew|\bsplit\b|\bbreak\b|\bcut\b|swallow(ed)? (it |them |the \w+ )?whole|whole (tablet|capsule|pill)/, name: "crushing, splitting or chewing", head: /how should i (take|use)|administration/ },
  { q: /\b(sun|sunlight|sunburn|tanning)\b/, add: "sunlight sun photosensitivity", hit: /\bsun|photosensitiv|ultraviolet|tanning/, name: "sunlight" },
];

/** "my 10 year old" is about children, "my 80-year-old" about older adults. */
const ages = (q: string) =>
  q.replace(/\b(\d{1,3})[- ]?(?:years?|yrs?)(?:[- ]old)?\b/g, (_, n) => (+n < 18 ? " child " : +n >= 65 ? " elderly " : " "));

// Words that carry no topic but match label boilerplate ("safe and effective use").
const FILLER = /\b(safe|safely|okay|ok|fine|alright|normal|bad|good|really)\b/g;

/** The question plus label-vocabulary terms, used to score label sentences. */
export function searchQuery(question: string): string {
  const q = ages(question.toLowerCase());
  const extra = TOPICS.filter((t) => t.q.test(q)).map((t) => t.add);
  const core = q.replace(FILLER, " ").replace(/\s+/g, " ").trim();
  return [core || q, ...extra].join(" ");
}

/** Words that say nothing about what the question is about (they match almost any label). */
const GENERIC = new Set(`
take takes taking took taken drink drinks drinking drank use uses using used can could okay ok safe safely
fine alright normal bad good really medicine medicines medication medications meds med pill pills tablet
tablets capsule capsules caplet caplets drug drugs dose doses dosing it get gets got have know happen happens
need needs want still also much many day days daily time times thing things something anything everything
tell say says said mention mentioned label cause causes make makes feel like go going start starting
prescribed doctor pharmacist little bit lot every ever usually now today risk risks problem problems worry
question information yes way give gave right wrong long often while same put common most serious
possible main usual typical any some kind type
`.split(/\s+/).filter(Boolean));

export interface Concept {
  /** The user's own words, for "the label doesn't mention …". */
  name: string;
  /** Does a label sentence (lowercased, with its heading) cover it? */
  covers: (s: string) => boolean;
  /** Section headings about this topic (lowercased), if any. */
  head?: RegExp;
}

/**
 * What a question is about: everyday topics with their label wording, plus runs of other
 * content words ("grapefruit juice"). The medicine's own names and generic verbs are dropped.
 * A run of n words is covered by a sentence containing at least ⌈(n+1)/2⌉ of them.
 */
export function concepts(question: string, ownNames: string[]): Concept[] {
  let q = ages(question.toLowerCase().replace(/[’']/g, "'"));
  const out: Concept[] = [];
  for (const t of TOPICS) {
    const m = q.match(t.q);
    if (!m) continue;
    out.push({ name: t.name ?? m[0].trim(), covers: (s) => t.hit.test(s), head: t.head });
    q = q.replace(new RegExp(t.q.source, "g"), " | ");
  }
  const own = new Set(ownNames.flatMap((n) => contentTokens(n)));
  let run: string[] = [];
  const flush = () => {
    if (run.length) {
      const words = run.map((w) => contentTokens(w)[0]);
      const res = words.map((w) => new RegExp(`\\b${w.replace(/[^a-z0-9]/g, "")}`));
      const need = Math.ceil((run.length + 1) / 2);
      out.push({ name: run.join(" "), covers: (s) => res.filter((r) => r.test(s)).length >= need });
    }
    run = [];
  };
  for (const [w] of q.matchAll(/[a-z]+(?:-[a-z]+)*|[^a-z\s]+/g)) {
    const tok = /^[a-z]/.test(w) ? contentTokens(w)[0] : undefined;
    if (!tok || GENERIC.has(w) || own.has(tok) || tok.length < 3) flush();
    else run.push(w);
  }
  flush();
  return out;
}
