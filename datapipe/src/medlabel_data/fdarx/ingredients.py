"""Resolve active ingredients for every FDARxBench label (by SPL set id).

openFDA first (openfda.substance_name); DailyMed packaging.json as fallback;
the label's own "Active ingredient" text as a last resort.

Output: BUILD/fdarx/label_ingredients.json
  {set_id: {"drug_name", "ingredients": [...], "source": "openfda|dailymed|manual|none"}}
"""

import json
import re
from collections import Counter

from .. import labels, paths

OUT = paths.BUILD / "fdarx" / "label_ingredients.json"
MANUAL = paths.CONFIG / "fdarx_ingredient_overrides.json"


def main() -> None:
    labs = [json.loads(l) for l in open(paths.FDARX_LABELS)]
    set_ids = [l["set_id"] for l in labs]
    ofda = labels.openfda_by_set_ids(set_ids)
    manual = json.loads(MANUAL.read_text()) if MANUAL.exists() else {}
    out = {}
    for l in labs:
        sid = l["set_id"]
        rec = ofda.get(sid)
        ings, src = labels.label_ingredients(rec, None), "openfda"
        if not ings:
            ings, src = labels.label_ingredients(None, labels.dailymed_packaging(sid)), "dailymed"
        if sid in manual:
            ings, src = sorted(labels.base_ingredient(x) for x in manual[sid]), "manual"
        if not ings:
            src = "none"
        out[sid] = {"drug_name": l["drug_name"], "ingredients": ings, "source": src}
    _text_fallback(labs, out)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(Counter(v["source"] for v in out.values()))
    for sid, v in out.items():
        if v["source"] == "none":
            print("UNRESOLVED", sid, v["drug_name"])


def _text_fallback(labs: list[dict], out: dict) -> None:
    """For unresolved labels, find known ingredient names in the drug name and label text.

    Vocabulary = ingredients resolved for the other labels. Only shared ingredients can
    cause train/test overlap, so a vocabulary drawn from other labels is sufficient.
    Accepts terms in the drug name, plus the most frequent term in the text and any term
    mentioned at least 3 times and at least 30% as often as the top term.
    """
    vocab = {i for v in out.values() for i in v["ingredients"]}
    pats = {t: re.compile(r"\b" + re.escape(t) + r"\b", re.I) for t in vocab}
    for l in labs:
        v = out[l["set_id"]]
        if v["source"] != "none":
            continue
        name_hits = {t for t, p in pats.items() if p.search(l["drug_name"])}
        counts = Counter({t: len(p.findall(l["label_raw"])) for t, p in pats.items()})
        counts = Counter({t: c for t, c in counts.items() if c})
        text_hits = set()
        if counts:
            top = counts.most_common(1)[0][1]
            text_hits = {t for t, c in counts.items() if c == top or (c >= 3 and c >= 0.3 * top)}
        # Drop terms that are substrings of a longer accepted term (e.g. "estradiol" in "ethinyl estradiol").
        hits = name_hits | text_hits
        hits = {t for t in hits if not any(t != u and t in u for u in hits)}
        if hits:
            v["ingredients"], v["source"] = sorted(hits), "label_text"


if __name__ == "__main__":
    main()
