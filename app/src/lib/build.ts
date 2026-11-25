// Build-time switches, read from Vite env vars. The local build keeps the defaults (web search
// through the /api/search proxy, local or Hugging Face models). The public GitHub Pages build
// (npm run build:pages) sets VITE_WEB_SEARCH=off, because a static site has no search proxy and no
// API key, and VITE_MODELS=hf, because it has no /models/ server.

export interface BuildFlags {
  /** The web-search backup step can run (needs the search proxy). */
  webSearch: boolean;
  searchUrl: string;
  /** Only offer models with a Hugging Face model_url and model_lib_url. */
  hfModelsOnly: boolean;
}

export function buildFlags(env: Record<string, unknown> = {}): BuildFlags {
  return {
    webSearch: env.VITE_WEB_SEARCH !== "off",
    searchUrl: (typeof env.VITE_SEARCH_URL === "string" && env.VITE_SEARCH_URL) || "/api/search",
    hfModelsOnly: env.VITE_MODELS === "hf",
  };
}

export const FLAGS: BuildFlags = buildFlags(import.meta.env ?? {});

/** Models this build can load. */
export function loadable<T extends { model_url?: string; model_lib_url?: string }>(models: T[], flags: BuildFlags = FLAGS): T[] {
  return flags.hfModelsOnly ? models.filter((m) => m.model_url && m.model_lib_url) : models;
}

/** Whether the web-search step runs, and if not, why (a key of web.ts WEB_SKIP). */
export function webStep(settingOn: boolean, flags: BuildFlags = FLAGS): { run: boolean; off?: "off" | "local-only" } {
  if (!flags.webSearch) return { run: false, off: "local-only" };
  return settingOn ? { run: true } : { run: false, off: "off" };
}
