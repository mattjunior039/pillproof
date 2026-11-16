"""Polite, cached HTTP GET for openFDA and DailyMed."""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import paths

USER_AGENT = "waicy-medlabel-datapipe/0.1 (student research project)"
_last_call: dict[str, float] = {}
# openFDA without a key allows 240 requests/minute; DailyMed has no published limit.
MIN_INTERVAL = {"api.fda.gov": 0.3, "dailymed.nlm.nih.gov": 0.2}


def _cache_path(url: str, suffix: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    host = urllib.parse.urlparse(url).netloc.replace(":", "_")
    return paths.CACHE / "http" / host / f"{h}{suffix}"


def get(url: str, *, suffix: str = ".bin", use_cache: bool = True, retries: int = 4) -> bytes | None:
    """GET a URL. Returns None on 404. Responses are cached on disk by URL."""
    cp = _cache_path(url, suffix)
    if use_cache and cp.exists():
        data = cp.read_bytes()
        return None if data == b"__404__" else data
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(retries):
        wait = MIN_INTERVAL.get(host, 0.2) - (time.monotonic() - _last_call.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = b"__404__"
                break
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(data)
    return None if data == b"__404__" else data


def get_json(url: str, **kw) -> dict | None:
    data = get(url, suffix=".json", **kw)
    if data is None:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        # Error pages come back as HTML; don't keep them in the cache.
        _cache_path(url, ".json").unlink(missing_ok=True)
        return None
