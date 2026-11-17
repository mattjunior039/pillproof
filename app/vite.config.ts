import { defineConfig, type Plugin } from "vite";
import preact from "@preact/preset-vite";
import { VitePWA } from "vite-plugin-pwa";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Model weights and wasm libraries are served from outside the repo, with the same routes as
// gate1/scripts/serve.py: /models/<name>/resolve/main/<file> and /libs/<file>.
const MODELS_DIR = process.env.MODELS_DIR || path.join(os.homedir(), "waicy-work/models");
const CERTS = process.env.CERTS_DIR || path.join(os.homedir(), "waicy-work/certs");
const root = path.dirname(new URL(import.meta.url).pathname);

const TYPES: Record<string, string> = {
  ".json": "application/json", ".wasm": "application/wasm", ".bin": "application/octet-stream",
  ".txt": "text/plain", ".model": "application/octet-stream",
};

function localModels(): Plugin {
  const handler = (req: any, res: any, next: () => void) => {
    const url = decodeURIComponent((req.url || "").split("?")[0]);
    let file: string | null = null;
    let m = url.match(/^\/models\/([^/]+)\/resolve\/main\/(.+)$/);
    if (m) file = path.join(MODELS_DIR, "mlc", m[1], m[2]);
    else if ((m = url.match(/^\/libs\/([^/]+\.wasm)$/))) file = path.join(MODELS_DIR, "libs", m[1]);
    if (!file) return next();
    if (file.includes("..") || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.statusCode = 404;
      return res.end("not found");
    }
    res.setHeader("Content-Type", TYPES[path.extname(file)] || "application/octet-stream");
    res.setHeader("Content-Length", fs.statSync(file).size);
    res.setHeader("Cache-Control", "no-cache");
    fs.createReadStream(file).pipe(res);
  };
  return {
    name: "local-models",
    configureServer: (s) => { s.middlewares.use(handler); },
    configurePreviewServer: (s) => { s.middlewares.use(handler); },
  };
}

// onnxruntime-web's wasm is copied into public/ort so speech and search work offline
// (transformers.js would otherwise fetch it from a CDN).
function copyOrt(): Plugin {
  return {
    name: "copy-ort",
    buildStart() {
      const src = path.join(root, "node_modules/onnxruntime-web/dist");
      const dst = path.join(root, "public/ort");
      fs.mkdirSync(dst, { recursive: true });
      for (const f of ["ort-wasm-simd-threaded.asyncify.mjs", "ort-wasm-simd-threaded.asyncify.wasm"]) {
        const a = path.join(src, f), b = path.join(dst, f);
        if (fs.existsSync(a) && (!fs.existsSync(b) || fs.statSync(a).size !== fs.statSync(b).size)) fs.copyFileSync(a, b);
      }
    },
  };
}

const https = process.env.HTTPS
  ? { key: fs.readFileSync(path.join(CERTS, "server.key")), cert: fs.readFileSync(path.join(CERTS, "server.crt")) }
  : undefined;

export default defineConfig({
  resolve: { alias: { "@core": path.resolve(root, "../core") } },
  server: { host: true, port: 5173, https, fs: { allow: [path.resolve(root, "..")] } },
  preview: { host: true, port: Number(process.env.PORT || 4173), https },
  worker: { format: "es" },
  build: { target: "es2022", chunkSizeWarningLimit: 8000 },
  plugins: [
    copyOrt(),
    localModels(),
    preact(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      manifest: {
        name: "MedLabel: your medicine labels, explained",
        short_name: "MedLabel",
        description: "Answers questions about your medicines from their FDA labels, on your device.",
        start_url: "./",
        display: "standalone",
        background_color: "#ffffff",
        theme_color: "#0b3d91",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,mjs,css,html,png,svg,json,webmanifest}"],
        // transformers.js also emits an unused copy of the ORT wasm; ours lives in /ort and is cached on first use.
        globIgnores: ["assets/ort-wasm*"],
        maximumFileSizeToCacheInBytes: 40 * 1024 * 1024,
        navigateFallbackDenylist: [/^\/models\//, /^\/libs\//],
        runtimeCaching: [
          { urlPattern: /\/ort\/ort-wasm/, handler: "CacheFirst", options: { cacheName: "ort-runtime" } },
          { urlPattern: /^https:\/\/rxnav\.nlm\.nih\.gov\/REST\/displaynames/, handler: "StaleWhileRevalidate", options: { cacheName: "rxnav-names" } },
        ],
      },
    }),
  ],
});
