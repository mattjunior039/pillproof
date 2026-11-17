// Everyday wording -> label wording, for keyword search only. The model still sees the
// user's own question. People ask about "side effects" and "pregnant"; labels say
// "adverse reactions" and "pregnancy", which BM25 alone would miss.

const EXPANSIONS: [RegExp, string][] = [
  [/\bside[- ]?effects?\b/, "side effects adverse reactions"],
  [/\bpregnan\w*|\bexpecting\b/, "pregnancy pregnant fetus"],
  [/\bbreast[- ]?(feed\w*|fed|milk)|\bnursing\b/, "breastfeeding breast milk lactation nursing"],
  [/\b(miss|missed|missing|skip|skipped|forget|forgot|forgotten)\b/, "miss missed dose"],
  [/\b(food|meals?|eat|eating|empty stomach|breakfast|lunch|dinner|supper)\b/, "food meals"],
  [/\b(alcohol\w*|beer|wine|liquor|drunk)\b/, "alcohol alcoholic drinks"],
  [/\b(store|storage|stored|fridge|refrigerat\w*|temperature)\b/, "store storage temperature"],
  [/\b(overdose\w*|too (much|many)|extra (dose|pill|tablet)s?|double (dose|up)|took two)\b/, "overdose overdosage too much"],
  [/\b(kids?|child|children|teen\w*|toddler\w*)\b/, "children pediatric"],
  [/\b(elderly|older|seniors?)\b/, "elderly older geriatric"],
  [/\b(interact\w*|together|mix\w*|combin\w*|other (medicines|medications|drugs|meds|pills))\b/, "interactions other medicines"],
  [/\b(what is it for|used for|what does it do|treats?|why (am i|do i) take)\b/, "prescription medicine used to treat indications"],
  [/\b(how much|how many|dosage|how often)\b/, "dose dosage"],
  [/\b(ibuprofen|advil|motrin|naproxen|aleve|aspirin|nsaids?|painkillers?|pain relievers?)\b/, "nsaids nonsteroidal anti-inflammatory pain medicines"],
  [/\b(tylenol|acetaminophen|paracetamol)\b/, "acetaminophen pain medicines"],
  [/\b(drive|driving|sleepy|drowsy|dizzy|dizziness)\b/, "drowsiness dizziness driving machinery"],
  [/\ballerg\w*/, "allergic reaction hypersensitivity"],
  [/\bkidneys?\b/, "kidney renal"],
  [/\bliver\b/, "liver hepatic"],
  [/\b(stop|stopping|quit)\b/, "stop taking discontinue"],
  [/\b(crush\w*|chew\w*|split\w*|cut|break|swallow\w*)\b/, "crush chew split break swallow whole"],
  [/\b(sun|sunlight|sunburn|tanning)\b/, "sunlight sun photosensitivity"],
];

// Words that carry no topic but match label boilerplate ("safe and effective use").
const FILLER = /\b(safe|safely|okay|ok|fine|alright|normal|bad|good|really)\b/g;

/** The question plus label-vocabulary terms, used to score label sentences. */
export function searchQuery(question: string): string {
  const q = question.toLowerCase();
  const extra = EXPANSIONS.filter(([re]) => re.test(q)).map(([, words]) => words);
  const core = q.replace(FILLER, " ").replace(/\s+/g, " ").trim();
  return [core || q, ...extra].join(" ");
}
