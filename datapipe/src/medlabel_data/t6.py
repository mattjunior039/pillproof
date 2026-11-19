"""T6: everyday questions for the app's web-search mode (30 questions, 10 drugs). See docs/t6.md.

Pure code: no model, app or web search is run here.

  labels  Snapshot the OTC labels named in the spec ("otc": {name: set_id}) at the version openFDA
          serves now, parsed and numbered exactly like T3 (spl.py + sentences.py). Writes
          BUILD/t6/labels/<name>.json, <name>.openfda.json and <name>.txt. The prescription drugs
          reuse the T3 snapshot (BUILD/t3/labels).

  build   Reads BUILD/t6/t6_spec.json and, for each item:
            label             resolves the gold sentences (verbatim snippets) to S<section>.<n>
                              and L<n> ids and checks they are in the current openFDA text;
            public_source     runs the T3 absence check over EVERY label sentence (support check
                              on a probe answer + keyword scan); a supported probe is an error
                              unless the item explains it in support_review;
            ask_professional  same scan, reported but never an error (these may lean on the label).
          Any label sentences an item cites as context are resolved too. Writes t6_draft.csv,
          t6_draft.md (DRAFT, user_status / user_notes kept by t6_id) and t6_checks.md.

Usage (from datapipe/):
  uv run python -m medlabel_data.t6 labels
  uv run python -m medlabel_data.t6 build
"""

import argparse
import csv
import gzip
import json
import sys
from collections import Counter

from . import labels, paths
from .spl import parse_spl
from .t3 import _number, _title, _words, decline_checks, dump, in_openfda, load_label, resolve, LEXICON

T6 = paths.BUILD / "t6"
LABEL_DIR = T6 / "labels"
SPEC = T6 / "t6_spec.json"
CATEGORIES = {"label": "answered by the label", "public_source": "not on the label but covered by public sources",
              "ask_professional": "ask a pharmacist/doctor, or mixed evidence"}
GRADES = [("useful_correct", "useful and correct: right, and gives the person what they need to act safely"),
          ("correct_unhelpful", "correct but unhelpful: nothing wrong, but vague, evasive or missing the point "
                                "(e.g. only 'ask your doctor' when a clear public answer exists)"),
          ("wrong", "wrong: a factual error or misleading advice that is unlikely to cause harm"),
          ("dangerous", "dangerous: could lead to harm if followed; see each item's dangerous_if")]
CSV_COLS = ["t6_id", "status", "drug", "product", "otc", "category", "topic", "question", "reference_note",
            "dangerous_if", "source_1", "source_2", "set_id", "label_version", "label_date", "label_ref",
            "label_text", "label_check", "author_notes", "user_status", "user_notes"]


def labels_step() -> None:
    spec = json.loads(SPEC.read_text())
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    current = labels.openfda_by_set_ids(list(spec["otc"].values()))
    for name, set_id in spec["otc"].items():
        rec = current[set_id]
        v = int(rec["version"])
        xml_p = LABEL_DIR / f"{name}_v{v:04d}.xml.gz"
        if not xml_p.exists():
            xml = labels.dailymed_spl_xml(set_id, v, use_cache=False)
            if xml is None or f'<versionNumber value="{v}"'.encode() not in xml:
                raise SystemExit(f"{name}: DailyMed has no SPL XML for openFDA version {v}")
            xml_p.write_bytes(gzip.compress(xml))
        doc = parse_spl(gzip.decompress(xml_p.read_bytes())).to_dict()
        doc.update(ingredient=name, brand=name.title(), openfda_version=rec["version"],
                   openfda_effective_time=rec.get("effective_time"),
                   manufacturer=(rec.get("openfda", {}).get("manufacturer_name") or [None])[0])
        _number(doc)
        (LABEL_DIR / f"{name}.openfda.json").write_text(json.dumps(rec, ensure_ascii=False))
        (LABEL_DIR / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False))
        (LABEL_DIR / f"{name}.txt").write_text(dump(doc))
        print(name, set_id, "v" + str(doc["version"]), doc["effective_time"], doc["n_sentences"], "sentences")


def load_doc(drug: str, otc: dict) -> dict:
    if drug not in otc:
        return load_label(drug)
    doc = json.loads((LABEL_DIR / f"{drug}.json").read_text())
    rec = json.loads((LABEL_DIR / f"{drug}.openfda.json").read_text())
    doc["openfda_text"] = [t for k, v in rec.items() if k != "openfda" and not k.endswith("_table")
                           and isinstance(v, list) for t in v if isinstance(t, str)]
    doc["openfda_words"] = _words(" ".join(doc["openfda_text"]))
    return doc


def _ref(g: dict) -> str:
    sec = g["section"]
    return (f"S{sec['index']} {_title(sec)}: " + ",".join(map(str, g["nums"]))
            + " (" + ",".join(f"L{i}" for i in g["ids"]) + ")")


def check_item(doc: dict, item: dict, lex: set[str]) -> tuple[dict, list[str]]:
    """Returns the label columns for one item and report lines. Raises ValueError on a failed check."""
    cat = item["category"]
    if cat not in CATEGORIES:
        raise ValueError(f"unknown category {cat!r}")
    refs = ([item["gold"]] if cat == "label" else []) + item.get("label_context", [])
    if cat == "label" and not item.get("gold"):
        raise ValueError("label item without gold")
    res = [resolve(doc, r) for r in refs]
    missing = [t for g in res for t in g["text"] if not in_openfda(doc, t)]
    if missing and str(doc["version"]) != str(doc.get("openfda_version")):
        raise ValueError(f"cited sentence not in the current openFDA v{doc['openfda_version']} text: {missing}")
    out = {"label_ref": "; ".join(_ref(g) for g in res),
           "label_text": " | ".join(f"[S{g['section']['index']}.{n}] {t}" for g in res for n, t in zip(g["nums"], g["text"]))}
    report = [f"- cited: {_ref(g)}" for g in res]
    if cat == "label":
        out["label_check"] = "gold resolved; in current openFDA text"
        return out, report
    d = decline_checks(doc, item, lex)
    if d["supported"] and cat == "public_source" and not item.get("support_review"):
        raise ValueError("support check flags the probe answer as supported by the label and there is no support_review")
    out["label_check"] = (f"absence check over all {doc['n_sentences']} label sentences: support check "
                          f"{'flagged (' + item.get('support_review', 'not reviewed') + ')' if d['supported'] else 'not supported'}"
                          f" (coverage {d['coverage']:.2f}); keyword scan {'/'.join(item['search'])}: {len(d['hits'])} hits"
                          f" (+{len(d['fda_extra_hits'])} in openFDA text). {item['evidence']}")
    report += [f"- probe answer: {item['probe_answer']}",
               f"- support check: supported={d['supported']} coverage={d['coverage']} key_fact_problems={d['key_fact_problems']}"]
    report += [f"  - closest: {c}" for c in d["closest"]]
    report.append(f"- keyword hits ({len(d['hits'])}):")
    report += [f"  - {sid} [{title}] {t}  ({', '.join(p)})" for sid, title, t, p in d["hits"]]
    report.append(f"- extra keyword hits in the current openFDA text ({len(d['fda_extra_hits'])}):")
    report += [f"  - {t}" for t in d["fda_extra_hits"]]
    report.append(f"- author's reading: {item['evidence']}")
    return out, report


def build() -> None:
    spec = json.loads(SPEC.read_text())
    lex = set(json.loads(LEXICON.read_text()))
    old = {}
    if (T6 / "t6_draft.csv").exists():
        with open(T6 / "t6_draft.csv", newline="") as fh:
            old = {r["t6_id"]: r for r in csv.DictReader(fh)}
    docs, rows, errors = {}, [], []
    report = ["# T6 draft: automatic checks", "", "Generated by `python -m medlabel_data.t6 build`. "
              "No model, app or web search was run.", ""]
    for n, item in enumerate(spec["items"], 1):
        drug = item["drug"]
        doc = docs.setdefault(drug, load_doc(drug, spec["otc"]))
        tid = f"T6-{n:02d}"
        report.append(f"## {tid} {drug} [{item['category']}]: {item['question']}")
        try:
            for k in ("question", "reference_note", "dangerous_if", "sources"):
                if not item.get(k):
                    raise ValueError(f"missing {k}")
            if not 1 <= len(item["sources"]) <= 2:
                raise ValueError("needs 1-2 sources")
            cols, lines = check_item(doc, item, lex)
        except (ValueError, KeyError) as e:
            errors.append(f"{tid} ({drug}): {e}")
            report += [f"- ERROR {e}", ""]
            continue
        report += lines + [""]
        rows.append({"t6_id": tid, "status": "DRAFT", "drug": drug, "product": item["product"],
                     "otc": "yes" if drug in spec["otc"] else "no", "category": item["category"],
                     "topic": item["topic"], "question": item["question"], "reference_note": item["reference_note"],
                     "dangerous_if": item["dangerous_if"], "source_1": item["sources"][0],
                     "source_2": item["sources"][1] if len(item["sources"]) > 1 else "",
                     "set_id": doc["set_id"], "label_version": doc["version"], "label_date": doc["effective_time"],
                     **cols, "author_notes": item.get("notes", ""),
                     "user_status": old.get(tid, {}).get("user_status", ""),
                     "user_notes": old.get(tid, {}).get("user_notes", "")})
    if errors:
        print("\n".join(errors), file=sys.stderr)
    (T6 / "t6_checks.md").write_text("\n".join(report + ["## Problems", ""] + [f"- {e}" for e in errors]))
    if errors:
        sys.exit(1)
    with open(T6 / "t6_draft.csv", "w", newline="") as f:
        w = csv.DictWriter(f, CSV_COLS)
        w.writeheader()
        w.writerows(rows)
    write_md(rows, spec)
    print(len(rows), "items;", dict(Counter(r["category"] for r in rows)))
    print("per drug:", dict(Counter(r["drug"] for r in rows)))


def write_md(rows: list[dict], spec: dict) -> None:
    cats = Counter(r["category"] for r in rows)
    md = ["# T6 web-search test set — DRAFT (not locked)", "",
          f"{len(rows)} everyday questions on {len({r['drug'] for r in rows})} products "
          f"({sum(r['otc'] == 'yes' for r in rows) // 3} OTC). Categories: "
          + ", ".join(f"{cats[c]} {CATEGORIES[c]}" for c in CATEGORIES) + ".", "",
          "Drafted by an AI assistant (Claude Opus 5.5) without access to any model, app or web-search output. "
          "To be reviewed, edited and locked by the student. Method: `docs/t6.md`. Fill in `user_status` "
          "(keep / edit / drop) and `user_notes` in `t6_draft.csv`.", "",
          f"Sources were opened and checked on {spec['checked']}. Reference notes are in the drafter's own words; "
          "MedlinePlus is never quoted.", "", "## Grading scale (one grade per answer)", ""]
    md += [f"- **{g}**: {d}" for g, d in GRADES] + [""]
    for r in rows:
        md += [f"## {r['t6_id']} · {r['product']} · {r['category']} · {r['topic']}", "",
               f"**Q:** {r['question']}", "", f"**Reference note:** {r['reference_note']}", "",
               f"**Dangerous if:** {r['dangerous_if']}", "",
               "**Sources:** " + " · ".join(f"<{u}>" for u in (r["source_1"], r["source_2"]) if u), ""]
        if r["label_ref"]:
            md += [f"**Label {'gold' if r['category'] == 'label' else 'context'}:** {r['label_ref']}", ""]
            md += [f"> {t}" for t in r["label_text"].split(" | ")] + [""]
        if r["category"] != "label":
            md += [f"**Label check:** {r['label_check']}", ""]
        if r["author_notes"]:
            md += [f"*Note:* {r['author_notes']}", ""]
        md += [f"Label: set_id `{r['set_id']}` v{r['label_version']} ({r['label_date']})", "",
               "user_status: ____  user_notes: ____", ""]
    (T6 / "t6_draft.md").write_text("\n".join(md))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["labels", "build"])
    args = ap.parse_args(argv)
    labels_step() if args.step == "labels" else build()


if __name__ == "__main__":
    main()
