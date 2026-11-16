"""Grade dev replies for Gate 2 (see docs/gate2.md for the rules).

    python train/scripts/grade_dev.py ~/waicy-work/eval/C2b_oracle.jsonl [...more runs]

Per item: parse with checks.check_reply (lenient parser; strict-format rate reported too).
  * invalid (unparseable, unfinished think, cites a number not in the prompt) -> error, counted wrong
  * expect decline: decline -> correct; answer -> wrong ("answered when it should have declined")
  * expect answerable: decline -> "declined when it should have answered"
      answer -> correct if the cited sentences are the right ones (select_ok) and, without
      checks, the restatement has no number/unit/drug missing from them. With checks a flagged
      restatement is blocked and only the quotes are shown, so only select_ok matters.
  * expect miss (retrieval lost the answer, prompt covers < 50% of it): decline -> correct,
      answer graded as for answerable.
select_ok: the cited sentences (plus their section headings) cover >= 70% of the answer tokens
the gold sentences cover, and at most max(2, |gold|) cited sentences are not gold.
Uncertainty: 95% bootstrap intervals resampling whole drug labels (2,000 resamples).
"""

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "datapipe" / "src"))
from medlabel_data.checks import check_reply  # noqa: E402
from medlabel_data.text import content_tokens, norm_ws  # noqa: E402

EVAL = Path("~/waicy-work/eval").expanduser()
LEX = set(json.loads((ROOT / "core" / "data" / "lexicon.json").read_text()))
SELECT_FRAC = 0.7
_LINE = re.compile(r"^\[(\d+)\] (.*)$")
_HEAD = re.compile(r"^\[Section(?:: (.*))?\]$")


def prompt_sentences(user: str):
    """{n: (sentence, heading)} from a rendered prompt."""
    out, head = {}, ""
    for line in user.split("\n"):
        if m := _HEAD.match(line):
            head = m.group(1) or ""
        elif m := _LINE.match(line):
            out[int(m.group(1))] = (m.group(2), head)
    return out


def grade_item(p: dict, reply: str) -> dict:
    sents = prompt_sentences(p["user"])
    r = check_reply(reply, {n: s for n, (s, _) in sents.items()}, p["drug"], LEX)
    g = {"status": r["status"], "strict": r["strict"], "n_cited": len(r["sentences"]), "blocked": r["blocked"],
         "problems": r["problems"], "select_ok": None, "exact": None, "p": None, "r": None}
    if r["status"] == "answer":
        ans = set(p["ans_tokens"])
        gold_text = {norm_ws(t) for t in p["gold_texts"]}
        cov = set()
        for n in r["sentences"]:
            s, h = sents[n]
            cov |= (set(content_tokens(s)) | set(content_tokens(h))) & ans
        cited_cov = len(cov) / len(ans) if ans else 0.0
        extra = sum(norm_ws(sents[n][0]) not in gold_text for n in r["sentences"])
        G = set(p["gold_nums"])
        g["select_ok"] = bool(cited_cov > 0 and cited_cov >= SELECT_FRAC * p["gold_cov"]
                              and extra <= max(2, len(p["gold_texts"])))
        if G:
            S = set(r["sentences"])
            g["exact"] = S == G
            g["p"] = len(S & G) / len(S)
            g["r"] = len(S & G) / len(G)
    exp = p["expect"]
    for mode in ("checks", "nochecks"):
        if r["status"] == "invalid":
            out = "invalid"
        elif exp == "decline":
            out = "correct" if r["status"] == "decline" else "wrong_answered"
        elif r["status"] == "decline":
            out = "correct" if exp == "miss" else "false_decline"
        else:
            ok = g["select_ok"] and (mode == "checks" or not r["problems"])
            out = "correct" if ok else "wrong"
        g[mode] = out
    return g


def summarize(prompts: list[dict], grades: list[dict], mode: str) -> dict:
    n = len(grades)
    o = [g[mode] for g in grades]
    exp = [p["expect"] for p in prompts]
    ans_i = [i for i, e in enumerate(exp) if e == "answerable"]
    dec_i = [i for i, e in enumerate(exp) if e == "decline"]
    answered = [g for g in grades if g["status"] == "answer"]
    sel = [g for g in answered if g["exact"] is not None]
    rate = lambda xs, k: round(sum(x == k for x in xs) / len(xs), 4) if xs else None  # noqa: E731
    wrong = sum(x in ("wrong", "wrong_answered", "invalid") for x in o)
    return {
        "n": n,
        "wrong_rate": round(wrong / n, 4),
        "correct_rate": rate(o, "correct"),
        "invalid_rate": rate(o, "invalid"),
        "false_decline_rate": rate([o[i] for i in ans_i], "false_decline"),
        "false_answer_rate": rate([o[i] for i in dec_i], "wrong_answered"),
        "answerable_correct": rate([o[i] for i in ans_i], "correct"),
        "select_ok": round(sum(g["select_ok"] for g in answered) / len(answered), 4) if answered else None,
        "select_exact": round(sum(g["exact"] for g in sel) / len(sel), 4) if sel else None,
        "select_p": round(sum(g["p"] for g in sel) / len(sel), 4) if sel else None,
        "select_r": round(sum(g["r"] for g in sel) / len(sel), 4) if sel else None,
        "block_rate": round(sum(g["blocked"] for g in answered) / len(answered), 4) if answered else None,
        "strict_rate": round(sum(g["strict"] for g in grades) / n, 4),
    }


def bootstrap(prompts, grades, mode, key, reps=2000, seed=0):
    by = {}
    for p, g in zip(prompts, grades):
        by.setdefault(p["set_id"], []).append((p, g))
    labs = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        pp, gg = [], []
        for s in (rng.choice(labs) for _ in labs):
            for p, g in by[s]:
                pp.append(p)
                gg.append(g)
        v = summarize(pp, gg, mode)[key]
        if v is not None:
            vals.append(v)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]


def load_run(path: Path):
    meta = json.loads(path.with_suffix(".meta.json").read_text())
    replies = {r["qid"] + r["kind"]: r for r in map(json.loads, open(path))}
    prompts = [p for p in map(json.loads, open(EVAL / f"prompts_{meta['prompts']}.jsonl"))
               if p["qid"] + p["kind"] in replies]
    grades = [grade_item(p, replies[p["qid"] + p["kind"]]["reply"]) for p in prompts]
    return meta, prompts, grades


def main():
    for arg in sys.argv[1:]:
        path = Path(arg).expanduser()
        meta, prompts, grades = load_run(path)
        res = {"run": path.stem, **{k: meta[k] for k in ("model", "adapter", "prompts", "n")}}
        for mode in ("checks", "nochecks"):
            s = summarize(prompts, grades, mode)
            s["wrong_rate_ci"] = bootstrap(prompts, grades, mode, "wrong_rate")
            res[mode] = s
        path.with_suffix(".grade.json").write_text(json.dumps(res, indent=1))
        with open(path.with_suffix(".graded.jsonl"), "w") as f:
            for p, g in zip(prompts, grades):
                f.write(json.dumps({"qid": p["qid"], "kind": p["kind"], "expect": p["expect"], "set_id": p["set_id"], **g}) + "\n")
        print(json.dumps(res))


if __name__ == "__main__":
    main()
