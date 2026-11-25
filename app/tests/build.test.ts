import { test } from "node:test";
import assert from "node:assert/strict";
import { buildFlags, loadable, webStep } from "../src/lib/build.ts";
import { WEB_SKIP } from "../src/lib/web.ts";

const local = buildFlags({});
const pages = buildFlags({ VITE_WEB_SEARCH: "off", VITE_MODELS: "hf" });

test("local build keeps web search and the setting decides", () => {
  assert.equal(local.webSearch, true);
  assert.equal(local.searchUrl, "/api/search");
  assert.deepEqual(webStep(true, local), { run: true });
  assert.deepEqual(webStep(false, local), { run: false, off: "off" });
  assert.equal(buildFlags({ VITE_SEARCH_URL: "https://w.example/api/search" }).searchUrl, "https://w.example/api/search");
});

test("public build never runs web search, even with the setting on", () => {
  assert.equal(pages.webSearch, false);
  for (const on of [true, false]) {
    const s = webStep(on, pages);
    assert.equal(s.run, false);
    assert.equal(s.off, "local-only");
    assert.match(WEB_SKIP[s.off!], /local version/);
  }
});

test("public build only offers models released on Hugging Face", () => {
  const models = [
    { key: "r1-ft", model_url: "https://huggingface.co/u/a", model_lib_url: "https://huggingface.co/u/a/x.wasm" },
    { key: "r2-ft" },
    { key: "half", model_url: "https://huggingface.co/u/b" },
  ];
  assert.deepEqual(loadable(models, pages).map((m) => m.key), ["r1-ft"]);
  assert.equal(loadable(models, local).length, 3);
});
