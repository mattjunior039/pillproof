"""Safety-section sentences for every downloaded version of a T3/T5 label.

Only the plan's safety sections are compared (plan section 3, item 15): boxed warning,
contraindications, warnings and precautions, drug interactions and the patient sections.
They are grouped so that both label formats line up:

| group         | PLR labels (2006 on)                         | older labels                              |
|---------------|----------------------------------------------|-------------------------------------------|
| boxed         | Boxed warning                                | Boxed warning                             |
| contra        | 4 Contraindications                          | CONTRAINDICATIONS                         |
| warnings      | 5 Warnings and precautions                   | WARNINGS, PRECAUTIONS (General, Lab tests)|
| interactions  | 7 Drug interactions                          | PRECAUTIONS > Drug Interactions           |
| patient       | 17 Patient counseling, Medication Guide,     | PRECAUTIONS > Information for Patients,   |
|               | Patient Information                          | Patient Information                       |

Under an old-format PRECAUTIONS section, subsections such as Pregnancy, Pediatric Use or
Carcinogenesis are not safety sections and are dropped; their own LOINC code (or title, when
the code is the generic 42229-5) decides. Instructions for Use (59845-8) are dropped too:
they describe how to handle the product, not safety.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..paths import CONFIG, LABELS
from ..sections import LOINC, classify_section
from ..sentences import split_sentences
from .normalize import is_admin, is_content, norm_key

GROUPS = {
    "boxed": "Boxed warning",
    "contra": "Contraindications",
    "warnings": "Warnings and precautions",
    "interactions": "Drug interactions",
    "patient": "Patient information",
}
GROUP_OF = {
    "boxed_warning": "boxed",
    "contraindications": "contra",
    "warnings_precautions": "warnings", "warnings": "warnings", "precautions": "warnings", "lab_tests": "warnings",
    "drug_interactions": "interactions",
    "patient_counseling": "patient", "medication_guide": "patient", "patient_info": "patient",
}
_OLD_SAFETY_PARENTS = {"warnings", "precautions", "warnings_precautions"}
_SKIP_CODES = {"59845-8"}  # Instructions for Use


@dataclass
class Unit:
    """One label sentence inside a safety group."""
    group: str
    section: str  # nearest titled section, e.g. "5.2 Bleeding"
    pos: int  # position within the group, in document order
    text: str  # sentence exactly as split from the label
    key: str  # normalized comparison key


@dataclass
class Version:
    version: int
    published: str  # ISO date DailyMed published this version
    effective: str | None  # label effective date (ISO)
    fmt: str  # "PLR" or "old"
    units: list[Unit]

    def by_group(self) -> dict[str, list[Unit]]:
        out: dict[str, list[Unit]] = {g: [] for g in GROUPS}
        for u in self.units:
            out[u.group].append(u)
        return out


def _iso(d: str | None, fmt: str) -> str | None:
    if not d:
        return None
    try:
        return datetime.strptime(d, fmt).date().isoformat()
    except ValueError:
        return None


def _effective_category(sec: dict, parent_cat: str | None, parent_spl_cat: str | None) -> str:
    """spl.py lets subsections inherit their parent's category. Under an old-format
    PRECAUTIONS section that would pull in Pregnancy, Pediatric Use and so on, so there a
    subsection's own specific LOINC code, or else its title, decides."""
    if sec["parent"] is None:
        return sec["category"]
    if parent_cat != "precautions":
        # keep spl.py's category unless the parent was re-assigned here
        return sec["category"] if parent_cat == parent_spl_cat else parent_cat
    code = sec.get("code")
    if code in LOINC and LOINC[code][0] != "unclassified":
        own = LOINC[code][0]
    elif sec.get("title"):
        own = classify_section(sec["title"], code)
    else:
        return parent_cat
    return parent_cat if own in _OLD_SAFETY_PARENTS or own == "other" else own


_TERMINAL = re.compile(r"[.!?:;][\"'”’)\]]*$")
_LIST_START = re.compile(r"^\s*(?:[•●▪◦■□○◆\-–—·*]|\(?(?:\d{1,2}|[a-z])[.)]\s)")
_JOIN_WORDS = {"a", "an", "the", "and", "or", "of", "to", "with", "in", "on", "for", "by", "at", "as",
               "is", "are", "be", "that", "which", "than", "from", "not", "may", "should", "if", "your"}


_GLUED = re.compile(r"(?<=[a-z]{2})\.(?=[A-Z][a-z])")


def reflow(text: str) -> str:
    """Join hard line breaks inside a sentence. Some older SPL files typeset each printed line
    with <br/>, and the line breaks move between versions. A line is joined to the previous one
    when the previous line has no closing punctuation and the line starts in lowercase, or the
    previous line ends in a comma, hyphen, open parenthesis or a function word. Bullet/list
    lines and table rows are never joined. A missing space after a full stop ("symptoms.Tell")
    is restored. Only whitespace changes; words are untouched."""
    out: list[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if out and "|" not in line and "|" not in out[-1] and not _LIST_START.match(line) \
                and not _TERMINAL.search(out[-1]):
            prev = out[-1]
            last = prev.rsplit(" ", 1)[-1].lower()
            if line[0].islower() or prev[-1] in ",-–(" or last in _JOIN_WORDS:
                out[-1] = prev + " " + line
                continue
        out.append(line)
    return _GLUED.sub(". ", "\n".join(out))


def safety_units(doc: dict) -> list[Unit]:
    secs = doc["sections"]
    eff: dict[int, str] = {}
    titled: dict[int, str] = {}
    counters = {g: 0 for g in GROUPS}
    out: list[Unit] = []
    for s in secs:
        p = s["parent"]
        cat = _effective_category(s, eff.get(p) if p is not None else None,
                                  secs[p]["category"] if p is not None else None)
        if s.get("code") in _SKIP_CODES or (p is not None and eff.get(p) == "_skip"):
            cat = "_skip"
        eff[s["index"]] = cat
        titled[s["index"]] = (s.get("title") or "").strip() or (titled.get(p, "") if p is not None else "")
        g = GROUP_OF.get(cat)
        if not g:
            continue
        name = titled[s["index"]] or GROUPS[g]
        for sent in split_sentences(reflow(s["text"])):
            k = norm_key(sent)
            if not k or is_admin(sent) or not is_content(sent):
                continue
            out.append(Unit(g, name, counters[g], sent, k))
            counters[g] += 1
    return out


def label_format(doc: dict) -> str:
    return "PLR" if any(s.get("code") == "43685-7" for s in doc["sections"]) else "old"


def load_drug(ingredient: str) -> tuple[dict, list[Version]]:
    """Manifest plus all versions, ordered by DailyMed publication date then version number."""
    root = LABELS / ingredient
    man = json.loads((root / "manifest.json").read_text())
    vdir = root / man["set_id"]
    # DailyMed's history sometimes lists one version number twice with two publication dates
    # (same file); keep the earliest date.
    first: dict[int, dict] = {}
    for v in man["versions"]:
        d = _iso(v.get("published_date"), "%b %d, %Y") or ""
        if v["version"] not in first or d < first[v["version"]]["_pub"]:
            first[v["version"]] = {**v, "_pub": d}
    versions = []
    for v in first.values():
        doc = json.loads((vdir / f"v{v['version']:04d}.json").read_text())
        versions.append(Version(
            version=v["version"],
            published=v["_pub"],
            effective=_iso(v.get("effective_time") or doc.get("effective_time"), "%Y%m%d"),
            fmt=label_format(doc),
            units=safety_units(doc),
        ))
    versions.sort(key=lambda x: (x.published, x.version))
    return man, versions


def drug_list() -> list[dict]:
    cfg = json.loads((CONFIG / "t3_drugs.json").read_text())
    return [d for d in cfg["drugs"] if (LABELS / d["ingredient"] / "manifest.json").exists()]


def lexicon() -> set[str]:
    """Lowercase ingredient and brand names of the 25 drugs, for the number/drug check."""
    out = set()
    for d in json.loads((CONFIG / "t3_drugs.json").read_text())["drugs"]:
        out.add(d["ingredient"].lower())
        if d.get("brand"):
            out.add(d["brand"].lower())
    return out


def versions_dir(ingredient: str) -> Path:
    return LABELS / ingredient
