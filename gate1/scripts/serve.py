"""HTTPS static server for the Gate 1 browser test.

Routes
  /                                 gate1/web/ (test page)
  /models/<name>/resolve/main/<f>   $WAICY_WORK/models/mlc/<name>/<f>  (WebLLM expects HF-style URLs)
  /libs/<f>                         $WAICY_WORK/models/libs/<f>         (cached WebLLM model libraries)
  /dev/<f>                          $WAICY_WORK/eval/web/<f>            (dev prompts for ?prompts=dev, not in git)
  /ca.crt                           local CA certificate, for installing on a phone
  POST /log                         append a JSON result line to $WAICY_WORK/logs/gate1-results.jsonl

WebGPU requires a secure context: localhost works over plain HTTP, but a phone on
the LAN needs HTTPS, hence the local CA (see docs/gate1.md for the openssl steps).

Usage: python serve.py [--port 8443] [--host 0.0.0.0]
"""

import argparse
import json
import os
import ssl
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

WORK = Path(os.environ.get("WAICY_WORK", Path.home() / "waicy-work"))
WEB = Path(__file__).resolve().parent.parent / "web"
MODELS = WORK / "models" / "mlc"
LIBS = WORK / "models" / "libs"
CERTS = WORK / "certs"
LOG = WORK / "logs" / "gate1-results.jsonl"


def _safe_join(root: Path, rel: str) -> str:
    p = (root / rel).resolve()
    if p != root.resolve() and root.resolve() not in p.parents:
        return str(root / "__forbidden__")
    return str(p)


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = unquote(urlsplit(path).path)
        parts = path.lstrip("/").split("/")
        if parts[0] == "models" and len(parts) >= 5 and parts[2:4] == ["resolve", "main"]:
            return _safe_join(MODELS / parts[1], "/".join(parts[4:]))
        if parts[0] == "libs" and len(parts) == 2:
            return _safe_join(LIBS, parts[1])
        if parts[0] == "dev" and len(parts) == 2:
            return _safe_join(WORK / "eval" / "web", parts[1])
        if path == "/ca.crt":
            return str(CERTS / "ca.crt")
        return _safe_join(WEB, "/".join(parts))

    def end_headers(self):
        if self.path.endswith((".html", ".js", "/")):
            self.send_header("Cache-Control", "no-cache")
        if self.path == "/ca.crt":
            self.send_header("Content-Type", "application/x-x509-ca-cert")
        super().end_headers()

    def do_POST(self):
        if self.path != "/log":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            rec = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return
        rec["_server_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rec["_client"] = self.client_address[0]
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print("RESULT", json.dumps(rec)[:2000], flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        if "/models/" not in self.path:  # keep shard requests out of the log
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--http", action="store_true", help="plain HTTP (only secure on localhost)")
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(WEB)))
    if not args.http:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERTS / "server.crt", CERTS / "server.key")
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    scheme = "http" if args.http else "https"
    print(f"Serving {WEB} on {scheme}://{args.host}:{args.port}  (models from {MODELS})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
