"""T3: hand-written questions on the 25 T3/T5 drugs (plan section 7). See docs/t3.md.

Two steps, both pure code (no model is ever run here):

  snapshot  For each drug in config/t3_drugs.json, take the label set chosen by labelfetch and
            the version openFDA currently serves (the label the app would use, plan item 8).
            If that version is newer than the cached DailyMed history, it is downloaded.
            Writes BUILD/t3/labels/<ingredient>.json (sections with sentences.py sentences)
            and <ingredient>.txt, a readable dump where every sentence has two ids:
              S<section>.<n>  section index in the parsed SPL, sentence n within it (from 1)
              L<n>            running number over the whole label, sections in document order

  build     Reads the question spec BUILD/t3/t3_spec.json, resolves each answerable item's
            gold sentences (given as verbatim snippets) to ids, and checks:
              * every snippet matches exactly one sentence of the named section;
              * the reference answer passes the app's restatement check against the gold
                sentences (numbers, units, drug names; plan section 3);
              * each listed alternative location also resolves.
            For each not-answerable item it runs, over EVERY sentence of the label:
              * the decline support check (fdarx/support.py, nothing removed) on a probe
                answer, i.e. what the answer would say if the label had one;
              * a keyword scan with the item's search patterns.
            All hits are written to the report so the absence can be confirmed by reading.
            Writes t3_draft.csv / t3_draft.md (DRAFT, with user_status and user_notes columns)
            and t3_checks.md. Existing user_status / user_notes values are carried over by t3_id.

Usage (from datapipe/):
  uv run python -m medlabel_data.t3 snapshot
  uv run python -m medlabel_data.t3 build
"""

import argparse
import csv
import gzip
import json
import re
import sys

from . import labels, paths
from .fdarx.align import Label
from .fdarx.support import supported_elsewhere
from .labelfetch import DRUGS_CONFIG, slug
from .sentences import split_sentences
from .spl import parse_spl
from .text import restatement_problems

T3 = paths.BUILD / "t3"
LABEL_DIR = T3 / "labels"
SPEC = T3 / "t3_spec.json"
LEXICON = paths.REPO / "core" / "data" / "lexicon.json"
PATIENT_CATS = {"medication_guide", "patient_info"}

CSV_COLS = ["t3_id", "status", "drug", "brand", "set_id", "label_version", "label_date", "openfda_version", "topic",
            "answerable", "question", "gold_section", "gold_sentences", "gold_ids", "gold_text",
            "alt_gold", "gold_in_openfda", "reference_answer", "decline_evidence", "author_notes", "user_status", "user_notes"]


# ---------- snapshot ----------

def _number(doc: dict) -> dict:
    n = 1
    for s in doc["sections"]:
        if s["sentences"] != split_sentences(s["text"]):
            raise SystemExit(f"sentence mismatch in section {s['index']} of {doc['set_id']}")
        s["first_id"] = n
        n += len(s["sentences"])
    doc["n_sentences"] = n - 1
    return doc


def _title(s: dict) -> str:
    return s["title"] or f"(untitled {s['category']})"


def dump(doc: dict) -> str:
    out = [f"{doc['ingredient']} | {doc['title'][:120]}",
           f"set_id {doc['set_id']} version {doc['version']} effective {doc['effective_time']}"
           f" | manufacturer {doc.get('manufacturer')}", ""]
    for s in doc["sections"]:
        if not s["sentences"] and not s["title"]:
            continue
        out.append(f"=== S{s['index']} {_title(s)} [{s['category']}]"
                   + (f" (parent S{s['parent']})" if s["parent"] is not None else ""))
        for i, t in enumerate(s["sentences"], 1):
            out.append(f"L{s['first_id'] + i - 1} S{s['index']}.{i} {t}")
        out.append("")
    return "\n".join(out)


def snapshot() -> None:
    cfg = json.loads(DRUGS_CONFIG.read_text())
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    mans = {d["ingredient"]: json.loads((paths.LABELS / slug(d["ingredient"]) / "manifest.json").read_text())
            for d in cfg["drugs"]}
    current = labels.openfda_by_set_ids([m["set_id"] for m in mans.values()])
    summary = []
    for drug in cfg["drugs"]:
        m = mans[drug["ingredient"]]
        set_id = m["set_id"]
        rec = current.get(set_id) or {}
        cached = max(v["version"] for v in m["versions"] if "effective_time" in v)
        want = int(rec.get("version") or cached)
        # Always re-parse the XML with the current spl.py / sentences.py: some cached JSON files
        # were written by an older sentence splitter.
        xml_p = paths.LABELS / slug(drug["ingredient"]) / set_id / f"v{want:04d}.xml.gz"
        source = "cached"
        if not xml_p.exists():
            xml_p, source = LABEL_DIR / f"{slug(drug['ingredient'])}_v{want:04d}.xml.gz", "downloaded"
            if not xml_p.exists():
                xml = labels.dailymed_spl_xml(set_id, want, use_cache=False)
                if xml is not None and f'<versionNumber value="{want}"'.encode() in xml:
                    xml_p.write_bytes(gzip.compress(xml))
            if not xml_p.exists():
                # DailyMed can lag openFDA. Fall back to the newest SPL XML we have; build() then
                # checks every gold sentence against the current openFDA text.
                xml_p = paths.LABELS / slug(drug["ingredient"]) / set_id / f"v{cached:04d}.xml.gz"
                source = f"cached v{cached}: openFDA v{want} XML not on DailyMed"
        doc = parse_spl(gzip.decompress(xml_p.read_bytes())).to_dict()
        o = rec.get("openfda", {})
        doc.update(ingredient=drug["ingredient"], brand=drug.get("brand"), source=source,
                   openfda_version=rec.get("version"), openfda_effective_time=rec.get("effective_time"),
                   manufacturer=(o.get("manufacturer_name") or [None])[0],
                   has_patient_section=any(s["category"] in PATIENT_CATS and s["sentences"] for s in doc["sections"]))
        _number(doc)
        (LABEL_DIR / f"{slug(drug['ingredient'])}.openfda.json").write_text(json.dumps(rec, ensure_ascii=False))
        (LABEL_DIR / f"{slug(drug['ingredient'])}.json").write_text(json.dumps(doc, ensure_ascii=False))
        (LABEL_DIR / f"{slug(drug['ingredient'])}.txt").write_text(dump(doc))
        row = {k: doc.get(k) for k in ("ingredient", "set_id", "version", "effective_time", "source",
                                       "openfda_version", "manufacturer", "has_patient_section", "n_sentences")}
        summary.append(row)
        print(json.dumps(row), flush=True)
    (LABEL_DIR / "snapshot.json").write_text(json.dumps(summary, indent=1))


# ---------- build ----------

def load_label(ingredient: str) -> dict:
    doc = json.loads((LABEL_DIR / f"{slug(ingredient)}.json").read_text())
    rec = json.loads((LABEL_DIR / f"{slug(ingredient)}.openfda.json").read_text())
    doc["openfda_text"] = [t for k, v in rec.items() if k != "openfda" and not k.endswith("_table")
                           and isinstance(v, list) for t in v if isinstance(t, str)]
    doc["openfda_words"] = _words(" ".join(doc["openfda_text"]))
    return doc


def _words(t: str) -> str:
    return " " + " ".join(re.findall(r"\w+", t.lower())) + " "


def in_openfda(doc: dict, sentence: str) -> bool:
    """True if the sentence's words appear, in order and contiguous, in the label openFDA serves now.

    A leading list number ("1. Place ...") is ignored: openFDA's text drops list numbering.
    """
    return _words(re.sub(r"^\s*\d{1,2}\.\s+", "", sentence)) in doc["openfda_words"]


def find_section(doc: dict, ref) -> dict:
    """`ref` is a section index (int) or a regex matched against section titles (one match)."""
    if isinstance(ref, int):
        return doc["sections"][ref]
    hits = [s for s in doc["sections"] if s["title"] and re.search(ref, s["title"], re.I)]
    if len(hits) != 1:
        raise ValueError(f"section {ref!r}: {len(hits)} matches {[h['title'] for h in hits]}")
    return hits[0]


def resolve(doc: dict, loc: dict) -> dict:
    """loc = {"section": idx-or-regex, "snippets": [...]}, one snippet per gold sentence.

    A snippet is a verbatim substring that must occur in exactly one sentence of the
    section, or {"n": number, "text": substring} to pin a sentence whose wording
    repeats within the section (the substring is still verified).
    """
    sec = find_section(doc, loc["section"])
    nums = []
    for snip in loc["snippets"]:
        if isinstance(snip, dict):
            n, snip = snip["n"], snip["text"]
            if not (1 <= n <= len(sec["sentences"])) or snip not in sec["sentences"][n - 1]:
                raise ValueError(f"S{sec['index']} {sec['title']!r}: sentence {n} does not contain {snip!r}")
            nums.append(n)
            continue
        hit = [i for i, t in enumerate(sec["sentences"], 1) if snip in t]
        if len(hit) != 1:
            raise ValueError(f"S{sec['index']} {sec['title']!r}: snippet {snip!r} matches {len(hit)} sentences")
        nums.append(hit[0])
    nums = sorted(set(nums))
    return {"section": sec, "nums": nums, "ids": [sec["first_id"] + n - 1 for n in nums],
            "text": [sec["sentences"][n - 1] for n in nums]}


def _label_for_support(doc: dict) -> Label:
    chunks = [(s["title"] + "\n" if s["title"] else "") + "\n".join(s["sentences"])
              for s in doc["sections"] if s["sentences"]]
    return Label({"set_id": doc["set_id"], "drug_name": doc.get("brand") or doc["ingredient"], "chunks": chunks})


def all_sentences(doc: dict):
    for s in doc["sections"]:
        for i, t in enumerate(s["sentences"], 1):
            yield s, i, t


def decline_checks(doc: dict, item: dict, lex: set[str]) -> dict:
    lab = _label_for_support(doc)
    rec = {"target": item["probe_answer"], "question": item["question"],
           "drug_name": doc.get("brand") or doc["ingredient"]}
    sup = supported_elsewhere(rec, lab, set(), lex)
    closest = [f"{lab.passages[c][0] or '(no heading)'} :: {lab.passages[c][1][s]}" for c, s in sup["sentences"]]
    pats = [re.compile(p, re.I) for p in item["search"]]
    hits = [(f"S{s['index']}.{i}", _title(s), t, [p.pattern for p in pats if p.search(t)])
            for s, i, t in all_sentences(doc) if any(p.search(t) for p in pats)]
    seen = {_words(t) for _, _, t, _ in hits}
    fda_hits = [t for block in doc["openfda_text"] for t in split_sentences(block)
                if any(p.search(t) for p in pats) and _words(t) not in seen]
    return {"fda_extra_hits": fda_hits,"supported": sup["supported"], "coverage": sup["coverage"],
            "key_fact_problems": sup["key_fact_problems"], "closest": closest, "hits": hits}


def build() -> None:
    spec = json.loads(SPEC.read_text())
    lex = set(json.loads(LEXICON.read_text()))
    docs: dict[str, dict] = {}
    old = {}
    if (T3 / "t3_draft.csv").exists():
        with open(T3 / "t3_draft.csv", newline="") as fh:
            old = {r["t3_id"]: r for r in csv.DictReader(fh)}
    rows, errors, report = [], [], ["# T3 draft: automatic checks", "",
                                    "Generated by `python -m medlabel_data.t3 build`. No model was run.", ""]
    for n, item in enumerate(spec["items"], 1):
        ing = item["drug"]
        doc = docs.setdefault(ing, load_label(ing))
        tid = f"T3-{n:03d}"
        row = {"t3_id": tid, "status": "DRAFT", "drug": ing, "brand": doc.get("brand") or "",
               "set_id": doc["set_id"], "label_version": doc["version"], "label_date": doc["effective_time"],
               "openfda_version": doc.get("openfda_version"),
               "topic": item["topic"], "answerable": "yes" if item["answerable"] else "no",
               "question": item["question"],
               "author_notes": " ".join(filter(None, [item.get("notes", ""), (
                   f"Reference answer adds the generic name(s) {', '.join(item['allow_terms'])} "
                   "for the brand in the question.") if item.get("allow_terms") else ""])),
               "user_status": old.get(tid, {}).get("user_status", ""),
               "user_notes": old.get(tid, {}).get("user_notes", "")}
        report.append(f"## {tid} {ing}: {item['question']}")
        try:
            if item["answerable"]:
                g = resolve(doc, item["gold"])
                alts = [resolve(doc, a) for a in item.get("alt", [])]
                # the answer may restate the gold sentences, the drug's names and the user's own words;
                # allow_terms lists brand->generic names the reference answer adds (shown in author_notes)
                allow = item.get("allow_terms", [])
                probs = restatement_problems(item["answer"], "\n".join(
                    g["text"] + [doc.get("brand") or "", ing, item["question"]] + allow), lex)
                if probs:
                    raise ValueError(f"reference answer fails the restatement check: {probs}")
                missing = [t for t in g["text"] if not in_openfda(doc, t)]
                if missing and str(doc["version"]) != str(doc.get("openfda_version")):
                    raise ValueError(f"gold sentence not in the current openFDA v{doc['openfda_version']} text: {missing}")
                row.update(gold_section=f"S{g['section']['index']} {_title(g['section'])}",
                           gold_sentences=",".join(map(str, g["nums"])),
                           gold_ids=",".join(f"L{i}" for i in g["ids"]),
                           gold_text=" | ".join(f"[{k}] {t}" for k, t in zip(g["nums"], g["text"])),
                           alt_gold="; ".join(f"S{a['section']['index']} {_title(a['section'])}: "
                                              + ",".join(map(str, a["nums"])) for a in alts),
                           reference_answer=item["answer"], decline_evidence="",
                           gold_in_openfda="yes" if not missing else "no")
                report += [f"- gold S{g['section']['index']}.{g['nums']} ok; restatement check ok; "
                           f"in current openFDA text: {'yes' if not missing else 'NO ' + repr(missing)}", ""]
            else:
                d = decline_checks(doc, item, lex)
                if d["supported"] and not item.get("support_review"):
                    errors.append(f"{tid} ({ing}): support check flags the probe answer as supported and "
                                  "the item has no support_review")
                row.update(gold_section="", gold_sentences="", gold_ids="", gold_text="", alt_gold="",
                           gold_in_openfda="",
                           reference_answer=item["answer"],
                           decline_evidence=(f"support check over all {doc['n_sentences']} label sentences: "
                                             f"{'flagged as supported; ' + item['support_review'] if d['supported'] else 'not supported'}"
                                             f" (coverage {d['coverage']:.2f}); keyword scan "
                                             f"{'/'.join(item['search'])}: {len(d['hits'])} hits"
                                             f" (+{len(d['fda_extra_hits'])} in openFDA text). "
                                             + item["evidence"]))
                report += [f"- probe answer: {item['probe_answer']}",
                           f"- support check: supported={d['supported']} coverage={d['coverage']}"
                           f" key_fact_problems={d['key_fact_problems']}"]
                report += [f"  - closest: {c}" for c in d["closest"]]
                report.append(f"- keyword hits ({len(d['hits'])}):")
                report += [f"  - {sid} [{title}] {t}  ({', '.join(p)})" for sid, title, t, p in d["hits"]]
                report.append(f"- extra keyword hits in the current openFDA text ({len(d['fda_extra_hits'])}):")
                report += [f"  - {t}" for t in d["fda_extra_hits"]]
                report += [f"- author's reading: {item['evidence']}"]
                if item.get("support_review"):
                    report.append(f"- support flag review: {item['support_review']}")
                report.append("")
        except (ValueError, KeyError) as e:
            errors.append(f"{tid} ({ing}): {e}")
            report += [f"- ERROR {e}", ""]
            continue
        rows.append(row)
    if errors:
        print("\n".join(errors), file=sys.stderr)
    (T3 / "t3_checks.md").write_text("\n".join(report + ["## Problems", ""] + [f"- {e}" for e in errors]))
    if errors:
        sys.exit(1)
    with open(T3 / "t3_draft.csv", "w", newline="") as f:
        w = csv.DictWriter(f, CSV_COLS)
        w.writeheader()
        w.writerows(rows)
    write_md(rows, spec)
    stats(rows)


def write_md(rows: list[dict], spec: dict) -> None:
    n_no = sum(r["answerable"] == "no" for r in rows)
    md = ["# T3 test set — DRAFT (not locked)", "",
          f"{len(rows)} questions on {len({r['drug'] for r in rows})} drugs; {n_no} ({n_no / len(rows):.0%}) are "
          "**not answerable** from the drug's label.", "",
          "Drafted by an AI assistant (Claude Opus 5.5) without access to any system outputs. "
          "To be reviewed, edited and locked by the student; reference answers to be checked by a pharmacist. "
          "Method: `docs/t3.md`. Fill in `user_status` (keep / edit / drop) and `user_notes` in `t3_draft.csv`.", "",
          "Gold sentences: `S<section>` is the section index in the parsed label and the numbers are sentences "
          "within that section, numbered by `datapipe/src/medlabel_data/sentences.py` from 1. `L<n>` is the running "
          "number over the whole label. Full numbered labels: `labels/<ingredient>.txt`.", ""]
    for r in rows:
        md += [f"## {r['t3_id']} · {r['drug']} ({r['brand'] or 'generic'}) · {r['topic']} · "
               f"{'answerable' if r['answerable'] == 'yes' else 'NOT answerable'}", "",
               f"**Q:** {r['question']}", ""]
        if r["answerable"] == "yes":
            md += [f"**Gold:** {r['gold_section']}, sentences {r['gold_sentences']} ({r['gold_ids']})", ""]
            md += [f"> {t}" for t in r["gold_text"].split(" | ")]
            md += [""]
            if r["alt_gold"]:
                md += [f"**Also answered in:** {r['alt_gold']}", ""]
            md += [f"**Reference answer:** {r['reference_answer']}", ""]
        else:
            md += [f"**Reference answer:** {r['reference_answer']}", "",
                   f"**Why not answerable:** {r['decline_evidence']}", ""]
        if r["author_notes"]:
            md += [f"*Note:* {r['author_notes']}", ""]
        md += [f"Label: set_id `{r['set_id']}` v{r['label_version']} ({r['label_date']})", "",
               "user_status: ____  user_notes: ____", ""]
    (T3 / "t3_draft.md").write_text("\n".join(md))


def stats(rows: list[dict]) -> None:
    from collections import Counter
    print(len(rows), "items;", Counter(r["answerable"] for r in rows))
    print("per drug:", dict(Counter(r["drug"] for r in rows)))
    print("topics:", dict(Counter(r["topic"] for r in rows)))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["snapshot", "build"])
    args = ap.parse_args(argv)
    snapshot() if args.step == "snapshot" else build()


if __name__ == "__main__":
    main()
