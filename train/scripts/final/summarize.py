"""Collect every final-evaluation number into final/summary.json (read by docs/final-eval.md).

    python3 train/scripts/final/summarize.py
Reads only finished outputs: final/t1 (Gate 2 grader), final/grades (T3 auto + AI grades),
final/t5/summary.json, final/app (app runs, E, A) and final/t1/retrieval.json. Nothing is re-run.
CIs: 95% bootstrap resampling whole drugs (T1: whole labels, as in Gate 2), 2,000 resamples.
"""
from __future__ import annotations

import csv
import json
import re
import statistics as st
from collections import Counter

from common import BUILD, FINAL, HYGIENE_QID, drug_boot, fk_grade, jl, paired_boot, rate

T1 = FINAL / "t1"
APP = FINAL / "app"
GR = FINAL / "grades"
WRONG = ("wrong", "wrong_answered", "invalid")


# ---------------------------------------------------------------- T1 (Gate 2 grader, unchanged)

def t1():
    out, rows = {}, {}
    for f in sorted(T1.glob("*.graded.jsonl")):
        run = f.name.split(".")[0]
        mode = "nochecks" if run.startswith("B") else "checks"
        rs = [{**r, "out": r[mode]} for r in jl(f)]
        rows[run] = rs
        meta = json.loads((T1 / f"{run}.meta.json").read_text()) if (T1 / f"{run}.meta.json").exists() else {}
        res = {"mode": mode, "seconds": meta.get("seconds"), "peak_gb": meta.get("peak_gb")}
        for sub, pick in (("primary", lambda r: r["kind"] != "fdarx_refusal"),
                          ("primary_no_hygiene", lambda r: r["kind"] != "fdarx_refusal" and r["qid"] != HYGIENE_QID),
                          ("fdarx_refusal", lambda r: r["kind"] == "fdarx_refusal")):
            s = [r for r in rs if pick(r)]
            ans = [r for r in s if r["expect"] == "answerable"]
            dec = [r for r in s if r["expect"] == "decline"]
            said = [r for r in s if r["status"] == "answer"]
            res[sub] = {
                "n": len(s),
                "correct": rate(s, lambda r: r["out"] == "correct"),
                "correct_ci": drug_boot(s, lambda x: rate(x, lambda r: r["out"] == "correct"), key="set_id"),
                "wrong": rate(s, lambda r: r["out"] in WRONG),
                "wrong_ci": drug_boot(s, lambda x: rate(x, lambda r: r["out"] in WRONG), key="set_id"),
                "answerable_n": len(ans), "answerable_correct": rate(ans, lambda r: r["out"] == "correct"),
                "false_decline": rate(ans, lambda r: r["out"] == "false_decline"),
                "decline_n": len(dec), "decline_correct": rate(dec, lambda r: r["out"] == "correct"),
                "miss_n": sum(r["expect"] == "miss" for r in s),
                "block_rate": rate(said, lambda r: r["blocked"]),
                "select_ok": rate(said, lambda r: bool(r["select_ok"])),
            }
            if sub == "primary" and run.startswith("C"):
                res[sub]["wrong_without_checks"] = rate(s, lambda r: r["nochecks"] in WRONG)
        out[run] = res
    diffs = {}
    for c, b in (("C2b_phone", "B2b_phone"), ("C08_phone", "B08_phone"), ("C2b_desktop", "B2b_desktop"),
                 ("C2b_oracle", "B2b_oracle"), ("C08_oracle", "B08_oracle"), ("C2b_phone", "C08_phone")):
        if c in rows and b in rows:
            A = {(r["qid"], r["kind"]): r for r in rows[c] if r["kind"] != "fdarx_refusal"}
            Bm = {(r["qid"], r["kind"]): r for r in rows[b] if r["kind"] != "fdarx_refusal"}
            ks = sorted(set(A) & set(Bm))
            ra, rb = [A[k] for k in ks], [Bm[k] for k in ks]
            for stat, fn in (("correct", lambda x: rate(x, lambda r: r["out"] == "correct")),
                             ("wrong", lambda x: rate(x, lambda r: r["out"] in WRONG))):
                diffs[f"{c}-{b}:{stat}"] = {"n": len(ks), "diff": round(fn(ra) - fn(rb), 4),
                                            "ci": paired_boot(ra, rb, fn, key="set_id")}
    out["paired"] = diffs
    rp = T1 / "retrieval.json"
    out["retrieval"] = json.loads(rp.read_text()) if rp.exists() else None
    return out, rows


# ---------------------------------------------------------------- AI grades

def drug_of(set_name):
    if set_name == "t3":
        return {r["t3_id"]: (r["drug"], r["answerable"] == "yes") for r in csv.DictReader(open(BUILD / "t3/t3_draft.csv"))}
    if set_name == "t2":
        return {r["id"]: (r["focus_drug"].lower(), None) for r in jl(FINAL / "t2/items.jsonl")}
    if set_name == "t6":
        return {r["t6_id"]: (r["drug"], None) for r in csv.DictReader(open(BUILD / "t6/t6_draft.csv"))}
    return {r["id"]: (r["drug"].lower(), True) for r in jl(T1 / "sample500.jsonl")}


def good(set_name, r):
    """Acceptable answer: correct; on a T3 item the label does not answer, an honest decline also counts."""
    if r["verdict"] == "correct":
        return True
    return set_name == "t3" and r["verdict"] == "declined" and r["answerable"] is False


def ai():
    out, all_rows = {}, {}
    for s in ("t3", "t2", "t6", "t1s"):
        f = GR / f"{s}.jsonl"
        if not f.exists():
            continue
        D = drug_of(s)
        rows = [{**r, "drug": D[r["id"]][0], "answerable": D[r["id"]][1]} for r in jl(f)]
        all_rows[s] = rows
        res = {}
        for sysname in sorted({r["system"] for r in rows}):
            x = [r for r in rows if r["system"] == sysname and r["verdict"]]
            c = Counter(r["verdict"] for r in x)
            e = {"n": len(x), "unparsed": sum(1 for r in rows if r["system"] == sysname and not r["verdict"]),
                 **{k: round(v / len(x), 4) for k, v in sorted(c.items())}}
            if s == "t6":
                e["useful_correct_ci"] = drug_boot(x, lambda y: rate(y, lambda r: r["verdict"] == "useful_correct"))
                e["dangerous_n"] = c.get("dangerous", 0)
            else:
                e["acceptable"] = rate(x, lambda r: good(s, r))
                e["acceptable_ci"] = drug_boot(x, lambda y: rate(y, lambda r: good(s, r)))
                e["wrong_ci"] = drug_boot(x, lambda y: rate(y, lambda r: r["verdict"] == "wrong"))
                e["harm_serious"] = rate(x, lambda r: r.get("harm") == "serious")
                e["harm_serious_n"] = sum(r.get("harm") == "serious" for r in x)
                if s == "t3":
                    a = [r for r in x if r["answerable"]]
                    u = [r for r in x if r["answerable"] is False]
                    e["answerable_correct"] = rate(a, lambda r: r["verdict"] == "correct")
                    e["unanswerable_declined"] = rate(u, lambda r: r["verdict"] == "declined")
                    e["unanswerable_wrong"] = rate(u, lambda r: r["verdict"] == "wrong")
            res[sysname] = e
        out[s] = res
    # paired differences on the AI grade
    pairs = {"t3": [("F2b", "E"), ("F08", "E"), ("C2b_phone", "B2b_phone"), ("C08_phone", "B08_phone"),
                    ("C2b_desktop", "B2b_desktop"), ("F2b", "C2b_desktop"), ("F08", "C08_phone"), ("C2b_phone", "E")],
             "t2": [("F2b", "E"), ("F08", "E"), ("C2b_phone", "B2b_phone"), ("C08_phone", "B08_phone"), ("F2b", "C2b_desktop")],
             "t6": [("F2b", "E"), ("F08", "E"), ("F2b", "C2b_desktop"), ("F08", "C08_phone")],
             "t1s": [("C2b_phone", "E"), ("C2b_phone", "B2b_phone"), ("E", "A2b")]}
    d = {}
    for s, ps in pairs.items():
        if s not in all_rows:
            continue
        key = "useful_correct" if s == "t6" else None
        fn = (lambda y: rate(y, lambda r: r["verdict"] == "useful_correct")) if key else (lambda y, s=s: rate(y, lambda r: good(s, r)))
        for a, b in ps:
            A = {r["id"]: r for r in all_rows[s] if r["system"] == a and r["verdict"]}
            Bm = {r["id"]: r for r in all_rows[s] if r["system"] == b and r["verdict"]}
            ids = sorted(set(A) & set(Bm))
            if not ids:
                continue
            ra, rb = [A[i] for i in ids], [Bm[i] for i in ids]
            d[f"{s}:{a}-{b}"] = {"n": len(ids), "diff": round(fn(ra) - fn(rb), 4), "ci": paired_boot(ra, rb, fn)}
    out["paired"] = d
    return out, all_rows


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def agreement(ai_rows, t1_rows):
    """AI grader vs the automatic (Gate 2-style) grader on the same answers: binary acceptable / not."""
    out = {}
    if "t3" in ai_rows and (GR / "t3_auto_rows.jsonl").exists():
        auto = {(r["run"], r["id"]): r for r in jl(GR / "t3_auto_rows.jsonl")}
        pairs = []
        for r in ai_rows["t3"]:
            a = auto.get((r["system"], r["id"]))
            if a and r["verdict"]:
                pairs.append((a["out"] == "correct", good("t3", r)))
        out["t3"] = {"n": len(pairs), "agree": rate(pairs, lambda p: p[0] == p[1]), "kappa": kappa(pairs),
                     "auto_ok_ai_not": sum(a and not b for a, b in pairs), "ai_ok_auto_not": sum(b and not a for a, b in pairs)}
    if "t1s" in ai_rows:
        pairs = []
        for run in ("B2b_phone", "C2b_phone"):
            g = {r["qid"]: r for r in t1_rows.get(run, []) if r["kind"] != "decline" and r["kind"] != "fdarx_refusal"}
            for r in ai_rows["t1s"]:
                if r["system"] == run and r["verdict"] and r["id"] in g:
                    pairs.append((g[r["id"]]["out"] == "correct", r["verdict"] == "correct"))
        out["t1s"] = {"n": len(pairs), "agree": rate(pairs, lambda p: p[0] == p[1]), "kappa": kappa(pairs),
                      "auto_ok_ai_not": sum(a and not b for a, b in pairs), "ai_ok_auto_not": sum(b and not a for a, b in pairs)}
    cs = GR / "calib_summary.json"
    out["gate2_decline_audit"] = json.loads(cs.read_text()) if cs.exists() else None
    p1 = GR / "calib_summary_pass1_max220.json"
    out["gate2_decline_audit_pass1_truncated"] = json.loads(p1.read_text()) if p1.exists() else None
    return out


# ---------------------------------------------------------------- app-run metrics (automatic)

def label_corpus(path, cache={}):
    if path not in cache:
        def walk(o):
            if isinstance(o, str):
                yield o
            elif isinstance(o, dict):
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        cache[path] = " ".join(" ".join(walk(json.load(open(path)))).split()).lower()
    return cache[path]


def _norm(s):
    return " ".join(re.sub(r"\s+", " ", s or "").split()).lower()


def app_metrics():
    out = {}
    items = {s: {r["id"]: r for r in jl(FINAL / s / "items_app.jsonl")} for s in ("t3", "t2", "t6")}
    for f in sorted(APP.glob("t*_*.jsonl")):
        s, run = f.stem.split("_", 1)
        if s not in items or run in ("E",) or run.startswith("A"):
            continue
        rows = jl(f)
        kinds = Counter(((r["first"] or {}).get("shown") or {}).get("kind", "none") for r in rows)
        res = {"n": len(rows), "shown_kind": dict(kinds)}
        quotes = [(r["id"], q["text"]) for r in rows for q in (((r["first"] or {}).get("shown") or {}).get("quotes") or [])]
        if quotes:
            ok = sum(_norm(q) in label_corpus(items[s][i]["label_file"]) for i, q in quotes)
            res["quote_verbatim_in_label"] = round(ok / len(quotes), 4)
            res["quotes_n"] = len(quotes)
        said = [((r["first"] or {}).get("shown") or {}) for r in rows if r["label_calls"]]
        ans = [x for x in said if x.get("kind") in ("answer", "quotes")]
        res["restatement_withheld"] = rate(ans, lambda x: x["kind"] == "quotes")
        res["declined"] = rate(rows, lambda r: (((r["first"] or {}).get("shown") or {}).get("kind")) in ("decline", "not-found"))
        res["fk_label_text"] = med([fk_grade(r["label_text"]) for r in rows])
        res["fk_restatement"] = med([fk_grade(x.get("restatement")) for x in said if x.get("kind") == "answer"])
        res["ms_median"] = med([r["ms"] for r in rows])
        res["ms_p90"] = pct([r["ms"] for r in rows], 0.9)
        secs = [c["seconds"] for r in rows for c in (r["label_calls"] or []) + (r.get("backup_calls") or []) if c.get("seconds")]
        res["model_seconds_median"] = med(secs)
        res["model_calls"] = len(secs)
        if "CF" in run:
            hits = [r for r in rows if (r.get("backup") or {}).get("hit")]
            res["backup_used"] = rate(rows, lambda r: bool((r.get("backup") or {}).get("hit")))
            res["backup_source"] = dict(Counter(r["backup"]["hit"]["source"].get("kind", "?") for r in hits))
            res["backup_error"] = sum(1 for r in rows if r.get("backup_error"))
            res["fk_shown_text"] = med([fk_grade(r["shown_text"]) for r in rows])
            res["source_link"] = rate(hits, lambda r: bool(r["backup"]["hit"]["source"].get("url")))
        m = f.with_suffix(".meta.json")
        if m.exists():
            res["meta"] = json.loads(m.read_text())
        out[f"{s}:{run}"] = res
    for f in sorted(APP.glob("t*_[AE]*.jsonl")):
        s, run = f.stem.split("_", 1)
        rows = jl(f)
        out[f"{s}:{run}"] = {"n": len(rows), "fk_reply": med([fk_grade(r.get("reply")) for r in rows]),
                             "words_median": med([len((r.get("reply") or "").split()) for r in rows]),
                             "truncated": sum(r.get("stop") == "max_tokens" for r in rows) if run == "E" else None}
    out["servers"] = {p.stem.split(".")[0]: json.loads(p.read_text()) for p in APP.glob("server_*.stats.json") if p.read_text().strip()}
    return out


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 2) if xs else None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def main():
    t1s, t1rows = t1()
    a, arows = ai()
    res = {"t1": t1s,
           "t3_auto": json.loads((GR / "t3_auto.json").read_text()) if (GR / "t3_auto.json").exists() else None,
           "ai": a, "agreement": agreement(arows, t1rows),
           "t5": json.loads((FINAL / "t5/summary.json").read_text()) if (FINAL / "t5/summary.json").exists() else None,
           "app": app_metrics()}
    cp = FINAL / "claude/cache.jsonl"
    if cp.exists():
        from claude import cost
        res["claude_spend_usd"] = round(cost(jl(cp)), 2)
    (FINAL / "summary.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1)[:6000])


if __name__ == "__main__":
    main()
