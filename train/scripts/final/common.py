"""Shared paths and helpers for the one-time final evaluation (docs/final-eval.md).

Nothing here changes the frozen app, models, retrieval, prompts or checks; it only reads them.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "datapipe" / "src"))
sys.path.insert(0, str(ROOT / "train" / "scripts"))

from medlabel_data import paths  # noqa: E402

BUILD = paths.BUILD
FINAL = BUILD / "final"
MODELS = Path("~/waicy-work/models").expanduser()
BASE = {"2b": MODELS / "Qwen3.5-2B", "08": MODELS / "Qwen3.5-0.8B"}
ADAPTER = {"2b": MODELS / "adapters" / "medlabel-2b-r1", "08": MODELS / "adapters" / "medlabel-08-r1"}
ENV = Path("~/waicy-work/.env").expanduser()
HYGIENE_QID = "bc83097f554e73b0"  # T1 item seen before the final run (docs/gate2.md)


def env_key(name: str) -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} not in {ENV}")


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p) if l.strip()]


def wjl(p: Path, rows) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- reading grade

_VOWELS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    w = word.lower().strip(".,;:!?\"'()")
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(_VOWELS.findall(w)))


def fk_grade(text: str) -> float | None:
    """Flesch-Kincaid grade level (own implementation, standard formula)."""
    text = (text or "").strip()
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if len(words) < 3:
        return None
    sents = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    syl = sum(syllables(w) for w in words)
    return round(0.39 * len(words) / sents + 11.8 * syl / len(words) - 15.59, 2)


# ---------------------------------------------------------------- resampling whole drugs

def drug_boot(rows: list[dict], stat, key="drug", reps=2000, seed=0):
    """95% interval of stat(rows) by resampling whole drugs."""
    by = {}
    for r in rows:
        by.setdefault(r[key], []).append(r)
    drugs = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        s = [r for d in (rng.choice(drugs) for _ in drugs) for r in by[d]]
        v = stat(s)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def paired_boot(rows_a: list[dict], rows_b: list[dict], stat, key="drug", reps=2000, seed=0):
    """95% interval of stat(a) - stat(b) on the same items, resampling whole drugs."""
    by = {}
    for a, b in zip(rows_a, rows_b):
        by.setdefault(a[key], []).append((a, b))
    drugs = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        pick = [p for d in (rng.choice(drugs) for _ in drugs) for p in by[d]]
        va, vb = stat([p[0] for p in pick]), stat([p[1] for p in pick])
        if va is not None and vb is not None:
            vals.append(va - vb)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def rate(rows, pred):
    return round(sum(1 for r in rows if pred(r)) / len(rows), 4) if rows else None
