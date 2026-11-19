// Web search proxy (docs/app.md, "Web search"): the browser sends only the active ingredient(s)
// and the question; this adds the Tavily key, which never reaches the browser.
// Shared by the Vite dev/preview servers (vite.config.ts) and the Cloudflare Worker (worker/).

/** Consumer health sites, searched first. */
export const CONSUMER_DOMAINS = [
  "medlineplus.gov", "nhs.uk", "fda.gov", "mayoclinic.org", "clevelandclinic.org", "drugs.com", "nih.gov",
  "cdc.gov", "webmd.com", "healthline.com", "rxlist.com", "medicinenet.com", "patient.info", "healthdirect.gov.au",
  "nps.org.au", "familydoctor.org", "kidshealth.org", "goodrx.com", "medicalnewstoday.com", "everydayhealth.com",
  "verywellhealth.com", "heart.org", "dailymed.nlm.nih.gov", "medsafe.govt.nz", "canada.ca", "hopkinsmedicine.org",
];

const MAX_RAW = 40000;
const TIMEOUT_MS = 15000;

/** Validates and normalizes the request; nothing else from the user's medicine list is accepted. */
export function cleanRequest(body) {
  const ingredients = Array.isArray(body?.ingredients) ? body.ingredients : [];
  const question = typeof body?.question === "string" ? body.question.replace(/\s+/g, " ").trim() : "";
  if (!ingredients.length || ingredients.length > 5) throw new Error("ingredients");
  const ing = ingredients.map((x) => String(x).toLowerCase().replace(/[^a-z0-9 ,.'()/-]/g, "").replace(/\s+/g, " ").trim());
  if (ing.some((x) => !x || x.length > 60)) throw new Error("ingredients");
  if (!question || question.length > 300) throw new Error("question");
  return { ingredients: ing, question };
}

export const cacheKey = (r) => `${r.ingredients.join("+")}|${r.question.toLowerCase().replace(/[^a-z0-9 ]/g, "")}`;

/** Simple limits: per client per minute, and per day overall (the free plan has 1,000 credits a month). */
export function limiter({ perMinute = 12, perDay = 300 } = {}) {
  const recent = new Map();
  let day = "", used = 0;
  return (ip, now = Date.now()) => {
    const d = new Date(now).toISOString().slice(0, 10);
    if (d !== day) { day = d; used = 0; }
    const ts = (recent.get(ip) || []).filter((t) => now - t < 60000);
    if (ts.length >= perMinute || used >= perDay) return false;
    ts.push(now);
    recent.set(ip, ts);
    used++;
    return true;
  };
}

async function tavily(key, fetchFn, body) {
  let last;
  for (let attempt = 0; attempt < 2; attempt++) {
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), TIMEOUT_MS);
    try {
      const r = await fetchFn("https://api.tavily.com/search", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
        body: JSON.stringify(body),
        signal: ac.signal,
      });
      if (r.status === 401 || r.status === 403) throw Object.assign(new Error("bad-key"), { fatal: true });
      if (r.status === 429 || r.status === 432 || r.status === 433) throw Object.assign(new Error("quota"), { fatal: true });
      if (!r.ok) throw new Error(`tavily ${r.status}`);
      const j = await r.json();
      if (j?.results?.length) return j.results;
      last = new Error("empty");
    } catch (e) {
      if (e.fatal) throw e;
      last = e;
    } finally {
      clearTimeout(t);
    }
  }
  if (last?.message === "empty") return [];
  throw last;
}

const shape = (r, tier) => ({
  url: String(r.url || ""),
  title: String(r.title || "").slice(0, 300),
  content: String(r.content || "").slice(0, 6000),
  raw: String(r.raw_content || "").slice(0, MAX_RAW),
  tier,
});

/**
 * One search: consumer health sites first; if fewer than 3 of those come back, an open search
 * over any site as well (the app ranks and labels them). 2 Tavily credits, 4 with the open search.
 */
export async function search(req, { key, fetchFn = fetch }) {
  const query = `${req.ingredients.join(" and ")}: ${req.question}`.slice(0, 380);
  const base = { query, search_depth: "advanced", max_results: 6, chunks_per_source: 3, include_raw_content: "text" };
  const out = (await tavily(key, fetchFn, { ...base, include_domains: CONSUMER_DOMAINS })).map((r) => shape(r, "consumer"));
  let credits = 2;
  if (out.length < 3) {
    credits += 2;
    const seen = new Set(out.map((r) => r.url));
    for (const r of await tavily(key, fetchFn, { ...base, max_results: 8 })) if (!seen.has(r.url)) out.push(shape(r, "open"));
  }
  return { query, credits, results: out.filter((r) => /^https?:\/\//.test(r.url)) };
}

/**
 * The whole endpoint, independent of the server: returns [status, json].
 * cache: { get(key) -> value | undefined, set(key, value) }.
 */
export async function handleSearch(body, { key, fetchFn, cache, allow, ip = "local" }) {
  if (!key) return [503, { error: "no-key" }];
  let req;
  try { req = cleanRequest(body); } catch (e) { return [400, { error: `bad-${e.message}` }]; }
  const k = cacheKey(req);
  const hit = await cache?.get(k);
  if (hit) return [200, { ...hit, cached: true }];
  if (allow && !allow(ip)) return [429, { error: "rate-limit" }];
  try {
    const res = { ...(await search(req, { key, fetchFn })), at: new Date().toISOString() };
    await cache?.set(k, res);
    return [200, res];
  } catch (e) {
    const m = String(e?.message || e);
    return [m === "bad-key" || m === "quota" ? 503 : 502, { error: m === "bad-key" || m === "quota" ? m : "search-failed" }];
  }
}
