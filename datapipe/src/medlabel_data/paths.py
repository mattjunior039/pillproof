"""Where data lives.

Large files stay out of git. Set WAICY_DATA to choose the root; otherwise
~/waicy-work/data is used if it exists, else <repo>/data.
"""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def data_root() -> Path:
    env = os.environ.get("WAICY_DATA")
    if env:
        return Path(env).expanduser()
    shared = Path("~/waicy-work/data").expanduser()
    if shared.is_dir():
        return shared
    return REPO / "data"


ROOT = data_root()
RAW = ROOT / "raw"
CACHE = ROOT / "cache"
LABELS = ROOT / "labels"
BUILD = ROOT / "build"

FDARX_DIR = RAW / "FDARxBench"
FDARX_QA = FDARX_DIR / "data" / "qa" / "qa.jsonl"
FDARX_LABELS = FDARX_DIR / "data" / "labels" / "labels.jsonl"
MEDQA_XLSX = RAW / "Medication_QA_MedInfo2019" / "MedInfo2019-QA-Medications.xlsx"

CONFIG = REPO / "datapipe" / "config"
