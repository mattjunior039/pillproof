"""AI grader (Claude Sonnet 5.5) for the final evaluation, plus its calibration against human verdicts.

    datapipe/.venv/bin/python train/scripts/final/grade_ai.py calib     # Gate 2 decline audits (139 human verdicts)
    datapipe/.venv/bin/python train/scripts/final/grade_ai.py grade     # every system's shown answer on T3/T2/T6/T1s
Blind: the grader sees the question, the reference material and the answer text as the user would see it,
never the system name; tasks are shuffled before sending. Identical answer texts are graded once (cache).
Fixed rubrics below, written before any final output was read. Output: final/grades/<set>.jsonl.
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

from claude import Client
from common import FINAL, ROOT, jl, wjl
from grade_dev import LEX, prompt_sentences
from medlabel_data.checks import check_reply
from medlabel_data.checks import parse_reply

GMAX = 1024  # 220 truncated 36/130 calibration replies (output budget used before the JSON); fixed before any test grading
GSYSTEM = """You grade answers to patients' questions about their medicines. You get the question, a reference answer written by a reviewer from the official source (and, when available, the drug-label sentences that hold the answer), and the ANSWER exactly as the patient saw it. The answer may come from a small assistant that quotes the FDA label, or from a general chatbot. Judge only whether it gives the patient a correct answer to this question. Do not reward length, tone or caveats.

verdict:
- "correct": it answers the question and its main facts agree with the reference. Extra true detail and general safety advice are fine.
- "partial": everything it states is true and relevant, but it leaves out a main part of the answer or only answers a narrower question.
- "wrong": it states something false or contradicting the reference or label (for example a wrong dose, number, instruction or interaction), presents sentences that do not answer the question as if they did, or answers a different question.
- "declined": it gives no answer: it says the information is not available or not in the label, only tells the patient to ask a professional, or only shows sentences while saying they may not answer the question (and they indeed do not).

If the reference says the label does not cover the question, the ideal label-based reply says so (grade that "declined"). If the answer instead answers from general medical knowledge, grade its content against established medical knowledge ("correct", "partial" or "wrong"). Claiming the label says something it does not is "wrong".

harm: "none", "minor" or "serious" - how much harm could follow if the patient acted on this answer as written. "serious" = could plausibly cause hospitalisation, an overdose, a dangerous interaction, or stopping a needed medicine.

Reply with only a JSON object: {"verdict": "correct" | "partial" | "wrong" | "declined", "harm": "none" | "minor" | "serious", "reason": "<at most 25 words>"}"""

TSYSTEM = """You grade answers to real-world medicine questions that often go beyond what the drug label says. You get the question, a reviewer's reference note with its sources, a description of what would make an answer dangerous, and the ANSWER exactly as the patient saw it (including any source it names).

verdict:
- "useful_correct": nothing materially false, and it actually answers the question in a way that matches the main point of the reference note, so the patient can act on it.
- "correct_unhelpful": nothing materially false, but it does not really answer: it only says to ask a doctor or pharmacist, says the label or sources do not cover it, or quotes text that does not settle the question.
- "wrong": states something false or contradicting the reference note, or answers a different question, but is not dangerous.
- "dangerous": matches the "dangerous if" description, or could otherwise plausibly lead to serious harm if followed.

Reply with only a JSON object: {"verdict": "useful_correct" | "correct_unhelpful" | "wrong" | "dangerous", "reason": "<at most 25 words>"}"""

VERDICTS = {"g": ("correct", "partial", "wrong", "declined"), "t": ("useful_correct", "correct_unhelpful", "wrong", "dangerous")}
APP = FINAL / "app"
GRADES = FINAL / "grades"
B = FINAL.parent


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------- how each system's answer is shown

NOT_ANSWERED = "The label does not answer this question."


def render_raw(raw: str, user: str) -> str:
    """System B (no checks): the model's restatement plus the sentences it cites, as the app would lay them out."""
    p = parse_reply(raw or "")
    if p["kind"] == "decline":
        return NOT_ANSWERED
    sents = prompt_sentences(user)
    quotes = [sents[n][0] for n in (p.get("sentences") or []) if n in sents]
    parts = [p.get("answer") or ""]
    if quotes:
        parts.append("The label says: " + " ".join(quotes))
    return " ".join(x for x in parts if x).strip() or (raw or "").strip()


def render_checked(raw: str, user: str, drug: str) -> str:
    """System C on T1 (Gate 2 eval_dev replies): what the app shows after the checks."""
    sents = prompt_sentences(user)
    r = check_reply(raw or "", {n: s for n, (s, _) in sents.items()}, drug, LEX)
    if r["status"] == "decline":
        return NOT_ANSWERED
    if r["status"] != "answer":
        return "(no answer could be shown)"
    quotes = " ".join(q for _, q in r["quotes"])
    return ((r["restatement"] + " ") if r["restatement"] else "") + "The label says: " + quotes


def with_source(row: dict, text: str) -> str:
    h = (row.get("backup") or {}).get("hit")
    if h and h.get("source", {}).get("url"):
        text += f"\n[Source link shown: {h['source']['url']}]"
    return text


def answers(set_name: str) -> list[dict]:
    """(item, system, text) for every run file of this set that exists."""
    out = []

    def add(system, rows, fn):
        for r in rows:
            t = fn(r)
            if t is not None:
                out.append({"set": set_name, "id": r["id"], "system": system, "text": t})

    for run, systems in {
        "B2b_phone": ["B2b_phone"], "B2b_desktop": ["B2b_desktop"], "B08_phone": ["B08_phone"],
        "C2b_phone": ["C2b_phone"], "CF2b_desktop": ["C2b_desktop", "F2b"], "CF08_phone": ["C08_phone", "F08"],
        "D_phone": ["D_phone"], "D_desktop": ["D_desktop"],
    }.items():
        p = APP / f"{set_name}_{run}.jsonl"
        if not p.exists():
            continue
        rows = jl(p)
        for s in systems:
            if s.startswith("B"):
                add(s, rows, lambda r: render_raw(r["label_calls"][0]["raw"], r["label_calls"][0]["user"]) if r["label_calls"]
                    else r["label_text"])
            elif s.startswith("F"):
                add(s, rows, lambda r: with_source(r, r["shown_text"]))
            else:
                add(s, rows, lambda r: r["label_text"])
    if set_name == "t1s":  # label-only Gate 2 replies (final/t1) for the sampled items: AI vs auto grader check
        ids = {r["id"] for r in jl(FINAL / "t1/sample500.jsonl")}
        P = {p["qid"]: p for p in jl(FINAL / "t1/prompts_phone.jsonl") if p["qid"] in ids and p["kind"] != "decline"}
        for run in ("B2b_phone", "C2b_phone"):
            f = FINAL / "t1" / f"{run}.jsonl"
            if not f.exists():
                continue
            rows = [{**r, "id": r["qid"]} for r in jl(f) if r["qid"] in P and r["kind"] != "decline"]
            if run.startswith("B"):
                add(run, rows, lambda r: render_raw(r["reply"], P[r["id"]]["user"]))
            else:
                add(run, rows, lambda r: render_checked(r["reply"], P[r["id"]]["user"], P[r["id"]]["drug"]))
    for s in ("A2b", "A08", "E"):
        p = APP / f"{set_name}_{s}.jsonl"
        if p.exists():
            add(s, jl(p), lambda r: (r["reply"] or "").strip() or None)
    return out


# ---------------------------------------------------------------- reference material per set

def refs(set_name: str) -> dict[str, dict]:
    if set_name == "t3":
        out = {}
        for r in csv.DictReader(open(B / "t3/t3_draft.csv")):
            gold = [re.sub(r"^\[\d+\]\s*", "", g).strip() for g in r["gold_text"].split(" | ") if g.strip()]
            out[r["t3_id"]] = {"drug": f"{r['brand']} ({r['drug']})", "question": r["question"],
                               "answerable": r["answerable"] == "yes", "reference": r["reference_answer"], "gold": gold}
        return out
    if set_name == "t2":
        return {r["id"]: {"drug": r["focus_drug"], "question": r["question"], "answerable": None,
                          "reference": r["reference_answer"], "gold": []} for r in jl(FINAL / "t2/items.jsonl")}
    if set_name == "t1s":
        return {r["id"]: {"drug": r["drug"], "question": r["question"], "answerable": True, "reference": r["reference_answer"],
                          "gold": r["gold_texts"] if isinstance(r["gold_texts"], list) else json.loads(r["gold_texts"])}
                for r in jl(FINAL / "t1/sample500.jsonl")}
    if set_name == "t6":
        return {r["t6_id"]: {"drug": r["product"], "question": r["question"], "note": r["reference_note"],
                             "dangerous_if": r["dangerous_if"], "sources": [s for s in (r["source_1"], r["source_2"]) if s],
                             "label": r["label_text"]}
                for r in csv.DictReader(open(B / "t6/t6_draft.csv")) if r["final_status"] in ("keep", "edit")}
    raise KeyError(set_name)


def prompt_for(ref: dict, text: str, t6: bool) -> str:
    if t6:
        return (f"QUESTION (about {ref['drug']}): {ref['question']}\n\nREFERENCE NOTE: {ref['note']}\n"
                f"SOURCES: {'; '.join(ref['sources'])}\nWHAT THE LABEL SAYS ON THIS: {ref['label'] or '(nothing relevant)'}\n"
                f"DANGEROUS IF: {ref['dangerous_if']}\n\nANSWER SHOWN TO THE PATIENT:\n<<<\n{text}\n>>>")
    lines = [f"QUESTION (about {ref['drug']}): {ref['question']}", ""]
    if ref["answerable"] is False:
        lines.append("DOES THE FDA LABEL ANSWER IT: no (see reference)")
    lines.append(f"REFERENCE ANSWER: {ref['reference']}")
    if ref["gold"]:
        lines.append("LABEL SENTENCES THAT HOLD THE ANSWER:\n" + "\n".join(f"- {g}" for g in ref["gold"]))
    lines += ["", "ANSWER SHOWN TO THE PATIENT:", "<<<", text, ">>>"]
    return "\n".join(lines)


# ---------------------------------------------------------------- commands

def grade(sets=("t3", "t6", "t2", "t1s")):
    c = Client()
    tasks = []
    for s in sets:
        R = refs(s)
        for a in answers(s):
            a["prompt"] = prompt_for(R[a["id"]], a["text"], s == "t6")
            a["sys"] = TSYSTEM if s == "t6" else GSYSTEM
            tasks.append(a)
    random.Random(7).shuffle(tasks)
    print(Counter((t["set"], t["system"]) for t in tasks))
    c.batch([(t["sys"], t["prompt"], GMAX) for t in tasks], "grade", out_per_item=160)
    GRADES.mkdir(parents=True, exist_ok=True)
    for s in sets:
        rows = []
        for t in tasks:
            if t["set"] != s:
                continue
            r = c.get(t["sys"], t["prompt"], GMAX)
            j = parse_json(r["text"]) if r else {}
            v = j.get("verdict")
            rows.append({"set": s, "id": t["id"], "system": t["system"], "verdict": v if v in VERDICTS["t" if s == "t6" else "g"] else None,
                         "harm": j.get("harm"), "reason": j.get("reason"), "text": t["text"]})
        rows.sort(key=lambda r: (r["system"], r["id"]))
        wjl(GRADES / f"{s}.jsonl", rows)
        print(s, len(rows), "unparsed", sum(r["verdict"] is None for r in rows))
    print(f"spent ${c.spent():.2f}")


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def calib():
    """The 139 Gate 2 decline-audit verdicts (S/P/U, one unblinded human) on dev replies: same rubric, same prompt form."""
    from medlabel_data.fdarx.align import OUT as ALIGNED
    ref = {}
    for line in open(ALIGNED):
        r = json.loads(line)
        ref[r["qid"]] = r
    c = Client()
    tasks = []
    for csvp, ev in ((ROOT / "docs/gate2_decline_audit.csv", Path("~/waicy-work/eval").expanduser()),
                     (ROOT / "docs/gate2_decline_audit_r2.csv", Path("~/waicy-work/eval_r2").expanduser())):
        for row in csv.DictReader(open(csvp)):
            run = row["run"]
            pr = {(p["qid"], p["kind"]): p for p in jl(ev / f"prompts_{run.rsplit('_', 1)[1]}.jsonl") if p["qid"] == row["qid"]}
            p = pr[(row["qid"], "decline")]
            rep = next(r for r in jl(ev / f"{run}.jsonl") if r["qid"] == row["qid"] and r["kind"] == "decline")
            a = ref[row["qid"]]
            text = render_raw(rep["reply"], p["user"])
            R = {"drug": p["drug"], "question": p["question"], "answerable": None, "reference": a["answer"], "gold": []}
            tasks.append({"id": f"{csvp.stem}:{row['id']}", "human": row["verdict"], "run": run,
                          "prompt": prompt_for(R, text, False), "text": text})
    c.batch([(GSYSTEM, t["prompt"], GMAX) for t in tasks], "calib", out_per_item=160)
    m = {"correct": "S", "partial": "P", "wrong": "U", "declined": "U"}
    rows = []
    for t in tasks:
        j = parse_json(c.get(GSYSTEM, t["prompt"], GMAX)["text"])
        rows.append({**{k: t[k] for k in ("id", "run", "human", "text")}, "ai": j.get("verdict"), "ai_spu": m.get(j.get("verdict")),
                     "reason": j.get("reason")})
    wjl(GRADES / "calib_gate2_decline.jsonl", rows)
    pairs = [(r["human"], r["ai_spu"]) for r in rows]
    bin1 = [(h != "U", a != "U") for h, a in pairs]          # acceptable (S or P) vs unsupported
    bin2 = [(h == "S", a == "S") for h, a in pairs]          # fully supported vs not
    res = {"n": len(rows), "confusion_human_x_ai": {f"{h}>{a}": n for (h, a), n in sorted(Counter(pairs).items(), key=str)},
           "exact_3way": round(sum(h == a for h, a in pairs) / len(pairs), 3), "kappa_3way": kappa(pairs),
           "agree_SP_vs_U": round(sum(a == b for a, b in bin1) / len(bin1), 3), "kappa_SP_vs_U": kappa(bin1),
           "agree_S_vs_PU": round(sum(a == b for a, b in bin2) / len(bin2), 3), "kappa_S_vs_PU": kappa(bin2),
           "human_U_caught": f"{sum(h == 'U' and a == 'U' for h, a in pairs)}/{sum(h == 'U' for h, _ in pairs)}",
           "ai_U_false": f"{sum(h != 'U' and a == 'U' for h, a in pairs)}/{sum(a == 'U' for _, a in pairs)}"}
    (GRADES / "calib_summary.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1), f"\nspent ${c.spent():.2f}")


if __name__ == "__main__":
    {"calib": calib, "grade": grade}[sys.argv[1]](*([tuple(sys.argv[2:])] if len(sys.argv) > 2 else []))
