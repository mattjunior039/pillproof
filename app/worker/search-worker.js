// Cloudflare Worker version of the web search proxy, for a public deployment later (not deployed).
// Deploy: `npx wrangler secret put TAVILY_API_KEY` then `npx wrangler deploy` from app/worker,
// and set the app's search URL to the Worker's /api/search (see docs/app.md, "Web search").
import { handleSearch, limiter } from "../server/search.js";

const allow = limiter({ perMinute: 6, perDay: 300 }); // per isolate; use a KV/Durable Object for strict limits
const CORS = { "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };

export default {
  async fetch(request, env, ctx) {
    const origin = env.ALLOWED_ORIGIN || "*";
    const headers = { ...CORS, "Access-Control-Allow-Origin": origin, "Content-Type": "application/json", "Cache-Control": "no-store" };
    if (request.method === "OPTIONS") return new Response(null, { headers });
    if (new URL(request.url).pathname !== "/api/search") return new Response('{"error":"not-found"}', { status: 404, headers });
    if (request.method !== "POST") return new Response('{"error":"method"}', { status: 405, headers });
    let body;
    try { body = await request.json(); } catch { return new Response('{"error":"bad-json"}', { status: 400, headers }); }
    // Cache API keyed by a synthetic URL: repeated questions cost no credits for 30 days.
    const cache = {
      get: async (k) => (await caches.default.match(`https://cache.local/${encodeURIComponent(k)}`))?.json(),
      set: (k, v) => ctx.waitUntil(caches.default.put(`https://cache.local/${encodeURIComponent(k)}`,
        new Response(JSON.stringify(v), { headers: { "Cache-Control": "max-age=2592000" } }))),
    };
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const [status, out] = await handleSearch(body, { key: env.TAVILY_API_KEY, fetchFn: fetch, cache, allow, ip });
    return new Response(JSON.stringify(out), { status, headers });
  },
};
