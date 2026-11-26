"""T7: fresh consumer questions for the v1.1 test (docs/v1.1.md). Pure code: no model is run here.

  labels  Copies the T3 label snapshot for the reused drugs and snapshots the pinned new labels at the
          version openFDA serves now, parsed and numbered exactly like T3. Writes BUILD/t7/labels/.
  build   Reads BUILD/t7/t7_spec.json (drafted items) and BUILD/t7/item_check.json (the second
          sub-agent's keep/drop marks) and runs the T3 checks on every item: gold snippets resolve to
          exactly one sentence, the reference answer passes the restatement check, gold is in the current
          openFDA text; for label-silent items the decline support check over all label sentences must not
          find the probe answer supported. Failing and dropped items are left out and listed in
          t7_checks.md. Writes t7_items.csv and the app item file items_app.jsonl.

Usage (from datapipe/):
  uv run python -m medlabel_data.t7 labels
  uv run python -m medlabel_data.t7 build
  uv run python -m medlabel_data.t7 check FILE   (read-only check of a draft spec file)
"""

import argparse
import csv
import gzip
import json
import re
import shutil
from collections import Counter

from . import labels, paths, t3
from .spl import parse_spl
from .t3 import _number, _title, _words, decline_checks, dump, in_openfda, resolve
from .text import restatement_problems

T7 = paths.BUILD / "t7"
LABEL_DIR = T7 / "labels"
SPEC = T7 / "t7_spec.json"
CHECK = T7 / "item_check.json"
CONFIG = paths.CONFIG / "t7_drugs.json"
COLS = ["t7_id", "drug", "brand", "in_t3", "otc", "set_id", "label_version", "label_date", "topic", "answerable",
        "question", "gold_section", "gold_sentences", "gold_ids", "gold_text", "reference_answer", "decline_evidence"]


def labels_step() -> None:
    cfg = json.loads(CONFIG.read_text())
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    for d in cfg["reuse_t3"]:
        for ext in (".json", ".openfda.json", ".txt"):
            shutil.copyfile(t3.LABEL_DIR / f"{d}{ext}", LABEL_DIR / f"{d}{ext}")
        print(d, "from T3 snapshot")
    new = cfg["new"]
    current = labels.openfda_by_set_ids([v["set_id"] for v in new.values()])
    for name, v in new.items():
        rec = current[v["set_id"]]
        ver = int(rec["version"])
        xml_p = LABEL_DIR / f"{name}_v{ver:04d}.xml.gz"
        if not xml_p.exists():
            xml = labels.dailymed_spl_xml(v["set_id"], ver, use_cache=False)
            if xml is None or f'<versionNumber value="{ver}"'.encode() not in xml:
                raise SystemExit(f"{name}: DailyMed has no SPL XML for openFDA version {ver}")
            xml_p.write_bytes(gzip.compress(xml))
        doc = parse_spl(gzip.decompress(xml_p.read_bytes())).to_dict()
        doc.update(ingredient=name, brand=v.get("brand"), openfda_version=rec["version"],
                   openfda_effective_time=rec.get("effective_time"),
                   manufacturer=(rec.get("openfda", {}).get("manufacturer_name") or [None])[0])
        _number(doc)
        (LABEL_DIR / f"{name}.openfda.json").write_text(json.dumps(rec, ensure_ascii=False))
        (LABEL_DIR / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False))
        (LABEL_DIR / f"{name}.txt").write_text(dump(doc))
        print(name, v["set_id"], "v" + str(doc["version"]), doc["effective_time"], doc["n_sentences"], "sentences")


def load(name: str) -> dict:
    doc = json.loads((LABEL_DIR / f"{name}.json").read_text())
    rec = json.loads((LABEL_DIR / f"{name}.openfda.json").read_text())
    doc["openfda_text"] = [t for k, v in rec.items() if k != "openfda" and not k.endswith("_table")
                           and isinstance(v, list) for t in v if isinstance(t, str)]
    doc["openfda_words"] = _words(" ".join(doc["openfda_text"]))
    return doc


def check(doc: dict, item: dict, lex: set[str]) -> tuple[dict, list[str]]:
    """Label columns for one item and report lines; raises ValueError on a failed check."""
    if item["answerable"]:
        g = resolve(doc, item["gold"])
        probs = restatement_problems(item["answer"], "\n".join(
            g["text"] + [doc.get("brand") or "", doc["ingredient"], item["question"]] + item.get("allow_terms", [])), lex)
        if probs:
            raise ValueError(f"reference answer fails the restatement check: {probs}")
        missing = [t for t in g["text"] if not in_openfda(doc, t)]
        if missing:
            raise ValueError(f"gold sentence not in the current openFDA text: {missing}")
        return ({"gold_section": f"S{g['section']['index']} {_title(g['section'])}",
                 "gold_sentences": ",".join(map(str, g["nums"])), "gold_ids": ",".join(f"L{i}" for i in g["ids"]),
                 "gold_text": " | ".join(f"[{k}] {t}" for k, t in zip(g["nums"], g["text"])), "decline_evidence": ""},
                [f"- gold S{g['section']['index']}.{g['nums']} ok; restatement ok; in openFDA text"])
    d = decline_checks(doc, item, lex)
    if d["supported"]:
        raise ValueError("support check finds the probe answer supported by the label")
    rep = [f"- probe answer: {item['probe_answer']}", f"- support check: not supported (coverage {d['coverage']:.2f})",
           f"- keyword hits ({len(d['hits'])}):"] + [f"  - {sid} [{t}] {s}" for sid, t, s, _ in d["hits"]]
    return ({"gold_section": "", "gold_sentences": "", "gold_ids": "", "gold_text": "",
             "decline_evidence": f"support check over all {doc['n_sentences']} sentences: not supported "
                                 f"(coverage {d['coverage']:.2f}); keyword scan {'/'.join(item['search'])}: "
                                 f"{len(d['hits'])} hits. {item.get('evidence', '')}"}, rep)


def build() -> None:
    cfg = json.loads(CONFIG.read_text())
    spec = json.loads(SPEC.read_text())
    marks = json.loads(CHECK.read_text()) if CHECK.exists() else {}
    lex = set(json.loads(t3.LEXICON.read_text()))
    docs, rows, report, dropped = {}, [], ["# T7: automatic item checks", "", "Generated by `python -m medlabel_data.t7 build`. No model was run.", ""], []
    for n, item in enumerate(spec["items"], 1):
        did = f"D{n:03d}"
        name = item["drug"]
        doc = docs.setdefault(name, load(name))
        report.append(f"## {did} {name}: {item['question']}")
        m = marks.get(did, {})
        try:
            if m.get("mark") == "drop":
                raise ValueError(f"dropped by the item check: {m.get('reason')}")
            cols, rep = check(doc, item, lex)
        except (ValueError, KeyError) as e:
            dropped.append(f"{did} ({name}): {e}")
            report += [f"- DROPPED: {e}", ""]
            continue
        report += rep + [f"- item check: {m.get('mark', 'not marked')} {m.get('reason', '')}", ""]
        new = cfg["new"].get(name, {})
        rows.append({"draft_id": did, "drug": name, "brand": doc.get("brand") or "", "in_t3": "yes" if name in cfg["reuse_t3"] else "no",
                     "otc": "yes" if new.get("otc") else "no", "set_id": doc["set_id"], "label_version": doc["version"],
                     "label_date": doc["effective_time"], "topic": item["topic"], "answerable": "yes" if item["answerable"] else "no",
                     "question": item["question"], "reference_answer": item["answer"], **cols})
    for i, r in enumerate(rows, 1):
        r["t7_id"] = f"T7-{i:03d}"
    (T7 / "t7_checks.md").write_text("\n".join(report + ["## Left out", ""] + [f"- {x}" for x in dropped]))
    with open(T7 / "t7_items.csv", "w", newline="") as f:
        w = csv.DictWriter(f, COLS + ["draft_id"])
        w.writeheader()
        w.writerows(rows)
    with open(T7 / "items_app.jsonl", "w") as f:
        for r in rows:
            lf = LABEL_DIR / f"{r['drug']}.openfda.json"
            f.write(json.dumps({"id": r["t7_id"], "question": r["question"], "label_file": str(lf), "drug": r["drug"],
                                **med_from(json.loads(lf.read_text()))}) + "\n")
    print(len(rows), "items kept,", len(dropped), "left out;", dict(Counter(r["answerable"] for r in rows)),
          "drugs", len({r["drug"] for r in rows}), "not in T3", len({r["drug"] for r in rows if r["in_t3"] == "no"}))
    for x in dropped:
        print("  left out:", x)


def med_from(rec: dict) -> dict:
    """The medicine as if the user had added this product (same as train/scripts/final/app_items.py)."""
    o = rec.get("openfda", {})
    g = re.sub(r"\([^)]*\)", "", (o.get("generic_name") or [""])[0].lower())
    parts = [p.strip() for p in re.split(r",|\band\b|/", g) if p.strip()]
    route = (o.get("route") or [""])[0]
    dfs = " ".join(rec.get("dosage_forms_and_strengths", []) + rec.get("description", [])).lower()
    if route == "ORAL":
        ci, ti = dfs.find("capsule"), dfs.find("tablet")
        form = "Oral " + ("Capsule" if ci >= 0 and (ti < 0 or ci < ti) else "Tablet")
    else:
        form = route.title()
    return {"ingredient": " / ".join(parts), "rxcui": (o.get("rxcui") or [""])[0], "form": form}


def check_file(path: str) -> None:
    """Read-only: run the build checks on a draft spec file and print one line per item."""
    lex = set(json.loads(t3.LEXICON.read_text()))
    docs, bad = {}, 0
    for n, item in enumerate(json.loads(open(path).read())["items"], 1):
        try:
            doc = docs.setdefault(item["drug"], load(item["drug"]))
            check(doc, item, lex)
            print(f"{n:3d} ok   {item['drug']}: {item['question']}")
        except (ValueError, KeyError, FileNotFoundError) as e:
            bad += 1
            print(f"{n:3d} FAIL {item.get('drug')}: {item.get('question')}\n       {e}")
    print(bad, "failing")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["labels", "build", "check"])
    ap.add_argument("spec", nargs="?")
    a = ap.parse_args(argv)
    if a.step == "check":
        check_file(a.spec)
    else:
        labels_step() if a.step == "labels" else build()


if __name__ == "__main__":
    main()
