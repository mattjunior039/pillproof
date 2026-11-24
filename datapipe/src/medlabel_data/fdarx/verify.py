"""AI verifier for round r4 training data (disclosed): fix false declines, keep r1's 30% decline share.

r4 starts from r1's train/valid rows (WAICY_DATA must point at the regenerated r1 data root, see
docs/data.md "Round 4"). Claude (MODEL) reads each example exactly as the small model sees it.

Decline rows (target NOT IN LABEL): Claude also gets the FDARxBench reference answer and the 12
closest sentences from the rest of the label (outside the removed and shown passages, marked E1..E12).
It says whether the shown sentences answer the question ("answers" / "partly" / "no"), the same for
the other sentences, and whether the question is unanswerable from any label ("bad_question"). A decline
is clean only if all three are no. A flagged decline is converted to an answerable row with Claude's
corrected target: SENTENCES from the shown sentences, or the E sentences' passages are added to the
prompt (re-rendered with build.render, passage budget kept by dropping uncited distractor passages),
and the reply must pass the app's checks (checks.check_reply). Otherwise the row is dropped.
The decline share is then restored to exactly r1's 30% with new decline candidates built the r1 way
(build.decline_example on questions from the same split's labels) that Claude marks clean.

Answerable rows: Claude checks SENTENCES/ANSWER (optional, `run --what answerable`).

T1 (test.jsonl) is never read. Responses are cached; re-runs are free.

Outcome (Nov 24): the verifier failed validation against the human verdicts, so r4 was not built and
r1 stays (docs/data.md "Round 4"). Only `validate` was run ($0.60).

Usage (from datapipe/, WAICY_DATA=~/waicy-work/r4/data_r1):
  python -m medlabel_data.fdarx.verify validate            # vs human audit verdicts (+ synthetic)
  python -m medlabel_data.fdarx.verify run --what declines --budget 20
  python -m medlabel_data.fdarx.verify run --what topup --budget 20
  python -m medlabel_data.fdarx.verify apply               # BUILD/fdarx/mlx_r4/{train,valid}.jsonl

The API key is read from ANTHROPIC_API_KEY or ~/waicy-work/.env and is never written anywhere.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import paths
from ..checks import check_reply, numbered_sentences, parse_reply
from ..text import content_tokens
from . import build, support
from .align import OUT as ALIGNED, _labels, answer_tokens
from .rewrite import _key

MODEL = "claude-sonnet-5-5"
PRICE_IN, PRICE_OUT = 2.0, 10.0  # USD per million tokens, list price; the Batch API bills half
PROMPT_VERSION = "v1"
SRC = paths.BUILD / "fdarx" / "mlx_plain"
OUT = paths.BUILD / "fdarx" / "verify"
CACHE = OUT / "cache.jsonl"
R4 = paths.BUILD / "fdarx" / "mlx_r4"
SPLITS = ("train", "valid")
SPLIT_OF_ROWS = {"train": "train", "valid": "dev"}  # aligned.jsonl split names
LEX = set(json.loads((paths.REPO / "core" / "data" / "lexicon.json").read_text()))
AUDIT = Path("~/waicy-work/data/build/fdarx/audit").expanduser()
R3_META = Path("~/waicy-work/data/build/fdarx/mlx_plain").expanduser()  # prompts the decline check showed
DECLINE = build.DECLINE
N_OTHER = 12
SHARE = build.DECLINE_SHARE

SYSTEM = """You check training examples for a small model that answers questions about a medicine using only numbered sentences from its FDA label. Each example shows the label sentences and question the model sees, and the target reply it is trained to give:
SENTENCES: <numbers of the sentences that answer the question>
ANSWER: <a short, plain restatement of those sentences>

Decide whether the target would teach the model something wrong. Most examples are fine. Mark "error" only for a clear, material problem of one of these kinds:
- wrong_sentences: the main fact in the ANSWER is not stated in any cited sentence (it is only in an uncited sentence, or nowhere), or most cited sentences have nothing to do with the question.
- wrong_answer: the ANSWER contradicts the cited sentences, claims something no shown sentence says, or does not answer the question that was asked.
- incomplete: the shown sentences clearly answer a main part of the question that the target leaves out entirely (for a two-part question, one whole part).

These are fine, do not mark them: plain or lay wording; a simpler or shorter answer that keeps the main facts; leaving out minor detail; one extra cited sentence that gives context (a list intro, a related warning); a minor detail taken from an uncited neighbouring sentence when the cited ones carry the main fact.

If you mark "error" and a correct target can be written from the shown sentences, give it in "fix": the sentence numbers that answer the question and a plain ANSWER (short sentences, everyday words) that uses only facts, numbers, units and drug names from those sentences. If the shown sentences do not answer the question, set "fix" to "NOT IN LABEL". If unsure, set "fix" to null.

Reply with only a JSON object:
{"verdict": "ok" or "error", "category": "ok", "wrong_sentences", "wrong_answer" or "incomplete", "reason": "<at most 25 words>", "fix": null or "NOT IN LABEL" or {"sentences": [numbers], "answer": "<text>"}}"""

DSYSTEM = """You check "decline" training examples for a small model that answers questions about a medicine using only numbered sentences from its FDA label. In a decline example the model is shown some label sentences and a question and is trained to reply NOT IN LABEL. That is only correct if the question cannot be answered from the label.

You get: the shown sentences and the question, exactly as the model sees them; the reference answer that was written from the full label; and other sentences from the same label that were not shown, marked E1, E2, ... (the closest matches to the reference answer).

Judge:
- "shown": do the shown sentences answer the question? "answers" = they state the main facts asked for, in any wording; "partly" = they state a real part of the answer (for example some of the warnings, strengths, steps or effects asked about); "no" = nothing in them answers the question (being on a related topic is not enough).
- "elsewhere": the same judgement for the E sentences, alone or together with the shown ones.
- "bad_question": true only if the question is unclear or asks for something a drug label cannot answer.

If "shown" or "elsewhere" is "answers" or "partly", write "fix": the sentences that answer the question (shown sentences as numbers, other sentences as strings like "E3"; use only shown sentences if they are enough) and a plain ANSWER in short sentences and everyday words that restates only what those sentences say. Use no facts, numbers, units or drug names from anywhere else, including the reference answer. Otherwise "fix" is null.

Reply with only a JSON object:
{"shown": "answers" or "partly" or "no", "elsewhere": "answers" or "partly" or "no", "bad_question": true or false, "reason": "<at most 25 words>", "fix": null or {"sentences": [3, "E2"], "answer": "<text>"}}"""


# ---------------------------------------------------------------- API client and cache

class Client:
    def __init__(self):
        import anthropic
        self.api = anthropic.Anthropic(api_key=_key(), max_retries=8)
        self.lock = threading.Lock()
        self.cache = {}
        OUT.mkdir(parents=True, exist_ok=True)
        if CACHE.exists():
            for line in open(CACHE):
                r = json.loads(line)
                self.cache[r["key"]] = r

    @staticmethod
    def key(system: str, prompt: str) -> str:
        return hashlib.sha256(f"{MODEL}|{PROMPT_VERSION}|{system}|{prompt}".encode()).hexdigest()

    def get(self, system: str, prompt: str) -> dict | None:
        return self.cache.get(self.key(system, prompt))

    def _store(self, rec: dict):
        with self.lock:
            self.cache[rec["key"]] = rec
            with open(CACHE, "a") as f:
                f.write(json.dumps(rec) + "\n")

    def ask(self, system: str, prompt: str) -> dict:
        k = self.key(system, prompt)
        if k in self.cache and self.cache[k]["text"]:
            return self.cache[k]
        resp = self.api.messages.create(model=MODEL, max_tokens=1200, system=system,
                                        messages=[{"role": "user", "content": prompt}])
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        rec = {"key": k, "text": out, "in": resp.usage.input_tokens, "out": resp.usage.output_tokens, "batch": False}
        self._store(rec)
        return rec

    def batch(self, items: list[tuple[str, str]], budget: float) -> None:
        """Send uncached (system, prompt) pairs through the Message Batches API (half price), wait, cache."""
        todo = {}
        for system, p in items:
            k = self.key(system, p)
            if k not in self.cache or not self.cache[k]["text"]:
                todo[k] = (system, p)
        spent = cost(self.cache.values())
        if not todo:
            print(f"nothing to send; spent so far ${spent:.2f}")
            return
        est = sum(len(s) + len(p) for s, p in todo.values()) / 3.3 * PRICE_IN / 2e6 + len(todo) * 160 * PRICE_OUT / 2e6
        print(f"{len(todo)} uncached prompts, estimated ${est:.2f} at batch price; spent so far ${spent:.2f}")
        if spent + est > budget:
            raise SystemExit(f"Estimate exceeds the ${budget:.0f} budget; nothing sent.")
        ids, reqs = {}, []
        for i, (k, (system, p)) in enumerate(todo.items()):
            ids[f"r{i}"] = k
            reqs.append({"custom_id": f"r{i}", "params": {"model": MODEL, "max_tokens": 1200,
                                                          "system": system,
                                                          "messages": [{"role": "user", "content": p}]}})
        b = self.api.messages.batches.create(requests=reqs)
        print("batch", b.id, flush=True)
        with open(OUT / "batch_ids.txt", "a") as f:
            f.write(b.id + "\n")
        while (b := self.api.messages.batches.retrieve(b.id)).processing_status != "ended":
            c = b.request_counts
            print(f"  {time.strftime('%H:%M:%S')} processing={c.processing} succeeded={c.succeeded} "
                  f"errored={c.errored}", flush=True)
            time.sleep(60)
        bad = 0
        for r in self.api.messages.batches.results(b.id):
            if r.result.type != "succeeded":
                bad += 1
                continue
            msg = r.result.message
            out = "".join(x.text for x in msg.content if x.type == "text").strip()
            self._store({"key": ids[r.custom_id], "text": out, "in": msg.usage.input_tokens,
                         "out": msg.usage.output_tokens, "batch": True})
        print(f"batch done; {bad} failed (rerun to retry); spent ${cost(self.cache.values()):.2f}")


def cost(recs) -> float:
    return sum((r["in"] * PRICE_IN + r["out"] * PRICE_OUT) / 1e6 * (0.5 if r.get("batch") else 1.0) for r in recs)


def _json(text: str) -> dict:
    if m := re.search(r"\{.*\}", text, re.S):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # Reply cut off inside "fix": salvage the scalar verdict fields, which come first.
    d = {k: v for k, v in re.findall(r'"(verdict|category|shown|elsewhere|reason)"\s*:\s*"((?:[^"\\]|\\.)*)"', text)}
    if m := re.search(r'"bad_question"\s*:\s*(true|false)', text):
        d["bad_question"] = m.group(1) == "true"
    return d


# ---------------------------------------------------------------- answerable rows

def user_prompt(user: str, target: str) -> str:
    return f"{user.strip()}\n\nTarget reply:\n{target.strip()}"


def parse_answerable(text: str) -> dict:
    d = _json(text)
    if d.get("verdict") not in ("ok", "error"):
        return {"verdict": "unparsed", "category": "unparsed", "reason": text[:200], "fix": None}
    return {"verdict": d["verdict"], "category": d.get("category") or d["verdict"], "reason": d.get("reason", ""),
            "fix": d.get("fix")}


def check_fix(fix, user: str, drug: str) -> str | None:
    """The corrected reply if it cites real sentences and passes the app's checks, else None."""
    if not isinstance(fix, dict):
        return None
    try:
        nums = sorted({int(n) for n in fix.get("sentences") or []})
    except (TypeError, ValueError):
        return None
    ans = re.sub(r"\s+", " ", str(fix.get("answer") or "")).strip()
    sents = numbered_sentences(user)
    if not nums or not ans or any(n not in sents for n in nums):
        return None
    reply = f"SENTENCES: {', '.join(map(str, nums))}\nANSWER: {ans}"
    r = check_reply(reply, sents, drug, LEX)
    return reply if r["status"] == "answer" and not r["blocked"] else None


# ---------------------------------------------------------------- decline rows

class Labels:
    def __init__(self):
        self.labs = _labels()
        self.recs = {}
        for line in open(ALIGNED):
            r = json.loads(line)
            self.recs.setdefault(r["qid"], r)


def _excuse(drug: str, lab) -> set[str]:
    return set(content_tokens(drug or "")) | set(content_tokens(lab.drug_name or ""))


def other_sentences(lab, rec: dict, drug: str, exclude: set[int], k: int = N_OTHER) -> list[tuple[int, int]]:
    """The k label sentences outside `exclude` that share most words with the reference answer."""
    ans = support.canon(answer_tokens(rec["target"], rec["question"], _excuse(drug, lab)))
    q = support.canon(set(content_tokens(rec["question"]))) - support.canon(_excuse(drug, lab))
    scored = []
    for c, s in support.remaining(lab, exclude):
        t = support.canon(lab.sent_tokens[c][s])
        a = len(t & ans)
        if a:
            scored.append((-(2 * a + len(t & q)), c, s))
    return sorted((c, s) for _, c, s in sorted(scored)[:k])


def decline_prompt(user: str, ref: str, lab, others: list[tuple[int, int]]) -> str:
    lines = []
    for i, (c, s) in enumerate(others, 1):
        head = lab.passages[c][0]
        lines.append(f"[E{i}] ({'Section: ' + head if head else 'no heading'}) {lab.passages[c][1][s]}")
    other = "\n".join(lines) if lines else "(none)"
    return (f"{user.strip()}\n\nReference answer (written from the full label):\n{ref.strip()}\n\n"
            f"Other sentences from the same label (not shown):\n{other}")


def parse_decline(text: str) -> dict:
    d = _json(text)
    ok = {"answers", "partly", "no"}
    if d.get("shown") not in ok or d.get("elsewhere") not in ok:
        return {"shown": "unparsed", "elsewhere": "unparsed", "bad_question": False, "reason": text[:200],
                "fix": None, "flag": False, "unparsed": True}
    d["bad_question"] = bool(d.get("bad_question"))
    d["flag"] = d["shown"] != "no" or d["elsewhere"] != "no" or d["bad_question"]
    return d


def decline_item(meta: dict, L: Labels) -> dict | None:
    """Everything needed to verify / convert one decline row (meta from *_meta.jsonl)."""
    rec = L.recs.get(meta["qid"])
    lab = L.labs.get(meta["set_id"])
    if rec is None or lab is None:
        return None
    user = meta["messages"][1]["content"]
    exclude = set(meta.get("removed") or []) | set(meta.get("passages") or [])
    others = other_sentences(lab, rec, meta["drug_name"], exclude)
    return {"meta": meta, "rec": rec, "lab": lab, "user": user, "others": others,
            "prompt": decline_prompt(user, rec["target"], lab, others)}


def _blocks_of(user: str, passages: list[int], lab) -> list[tuple[int, list[int]]] | None:
    """Recover build.render's blocks (chunk, sentence indices) from a rendered prompt."""
    body = user.split("\nLabel sentences:\n", 1)[1].rsplit("\nQuestion:", 1)[0]
    secs = [[re.sub(r"^\[\d+\] ", "", l) for l in part.split("\n")[1:] if re.match(r"\[\d+\] ", l)]
            for part in re.split(r"(?m)^(?=\[Section)", body) if part.strip()]
    if len(secs) != len(passages):
        return None
    blocks = []
    for c, texts in zip(passages, secs):
        sents = lab.passages[c][1]
        ids = []
        for t in texts:
            try:
                ids.append(sents.index(t, ids[-1] + 1 if ids else 0))
            except ValueError:
                return None
        blocks.append((c, ids))
    return blocks


def convert(it: dict, fix) -> tuple[str, str, dict] | None:
    """(user, target, info) for a flagged decline if the fix passes the app's checks, else None."""
    if not isinstance(fix, dict):
        return None
    meta, lab = it["meta"], it["lab"]
    shown, extra = set(), set()
    for x in fix.get("sentences") or []:
        if isinstance(x, int) or (isinstance(x, str) and x.strip().isdigit()):
            shown.add(int(x))
        elif isinstance(x, str) and re.fullmatch(r"E\d+", x.strip()):
            i = int(x.strip()[1:]) - 1
            if not 0 <= i < len(it["others"]):
                return None
            extra.add(it["others"][i])
        else:
            return None
    if not extra:
        reply = check_fix({"sentences": sorted(shown), "answer": fix.get("answer")}, it["user"], meta["drug_name"])
        return (it["user"], reply, {"r4_status": "converted_shown"}) if reply else None
    blocks = _blocks_of(it["user"], meta["passages"], lab)
    if blocks is None:
        return None
    old_num, n = {}, 1
    for c, ids in blocks:
        for s in ids:
            old_num[n] = (c, s)
            n += 1
    if any(x not in old_num for x in shown):
        return None
    cited = {old_num[x] for x in shown} | extra
    new = {}
    for c, s in sorted(extra):
        new.setdefault(c, []).append(s)
    rng = random.Random(f"r4-{meta['qid']}")
    for c, focus in new.items():
        ids = sorted(set(build.window(lab, c, focus, build.MAX_PASSAGE_CHARS)) | set(focus))
        blocks.insert(rng.randrange(len(blocks) + 1), (c, ids))
    size = lambda: sum(len(lab.passages[c][1][s]) for c, ids in blocks for s in ids)
    while len(blocks) > build.MAX_PASSAGES or size() > build.MAX_PROMPT_CHARS:
        spare = [b for b in blocks if not any((b[0], s) in cited for s in b[1])]
        if not spare:
            break
        blocks.remove(spare[-1])
    user, numbering, chars = build.render(lab, blocks, meta["drug_name"], meta["question"])
    nums = sorted(numbering[cs] for cs in cited)
    reply = check_fix({"sentences": nums, "answer": fix.get("answer")}, user, meta["drug_name"])
    if not reply:
        return None
    return user, reply, {"r4_status": "converted_added", "passages": [b[0] for b in blocks],
                         "answer_sentences": nums, "prompt_chars": chars}


def meta_rows(split: str, root: Path = SRC) -> list[dict]:
    return [json.loads(l) for l in open(root / f"{split}_meta.jsonl")]


def decline_items(L: Labels) -> list[dict]:
    out = []
    for sp in SPLITS:
        for i, m in enumerate(meta_rows(sp)):
            if m["kind"] == "decline":
                it = decline_item(m, L)
                if it is None:
                    raise SystemExit(f"no label/aligned record for decline {m['qid']}")
                out.append({**it, "split": sp, "i": i})
    return out


def topup_candidates(L: Labels, split: str, n: int, used: set[str]) -> list[dict]:
    """New decline rows built the r1 way (build.decline_example) from this split's own questions."""
    pool = [r for r in L.recs.values() if r["split"] == SPLIT_OF_ROWS[split] and r["qid"] not in used
            and not r.get("hard_fail") and r.get("coverage", 0) >= 0.5]
    random.Random(f"r4-topup-{split}").shuffle(pool)
    out = []
    for r in pool:
        if len(out) >= n:
            break
        lab = L.labs[r["set_id"]]
        removed = build.decline_removed(r, lab)
        if support.supported_elsewhere(r, lab, removed, LEX)["supported"]:
            continue
        ex = build.decline_example(r, lab, random.Random(f"r4-topup-{r['qid']}"))
        if ex is None:
            continue
        user, target, info = ex
        meta = {"kind": "decline", "tier": build.tier(r), "qid": r["qid"], "task": r.get("task"),
                "source": r.get("source"), "set_id": r["set_id"], "drug_name": r["drug_name"],
                "question": r["question"], "reference_answer": r["target"], "categories": r.get("categories"),
                "coverage": r.get("coverage"), **info, "r4_status": "topup",
                "messages": [{"role": "system", "content": build.SYSTEM}, {"role": "user", "content": user},
                             {"role": "assistant", "content": DECLINE}]}
        it = decline_item(meta, L)
        if it is not None:
            out.append({**it, "split": split})
    return out


def topup_need(split: str, flagged: int, converted: int) -> int:
    """Clean new declines needed so declines are exactly SHARE of the split after fixing."""
    rows_ = meta_rows(split)
    ans = sum(m["kind"] == "answerable" for m in rows_) + converted
    dec = sum(m["kind"] == "decline" for m in rows_) - flagged
    return max(0, round(ans * SHARE / (1 - SHARE)) - dec)


# ---------------------------------------------------------------- validation against the human audits

def _kappa(pairs: list[tuple[bool, bool]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def _synthetic(rows_: list[dict], rng: random.Random, n: int) -> list[dict]:
    """Corrupted answerable targets: cite non-answer sentences, or another question's answer."""
    by_set = {}
    for r in rows_:
        by_set.setdefault(r["set_id"], []).append(r)
    out = []
    for r in rng.sample(rows_, len(rows_)):
        if len(out) >= n:
            break
        p = parse_reply(r["messages"][-1]["content"])
        user = r["messages"][1]["content"]
        if p["kind"] != "answer":
            continue
        if len(out) % 2 == 0:
            near = {x + d for x in p["sentences"] for d in (-1, 0, 1)}
            cand = [x for x in numbered_sentences(user) if x not in near]
            if len(cand) < len(p["sentences"]):
                continue
            t = f"SENTENCES: {', '.join(map(str, sorted(rng.sample(cand, len(p['sentences'])))))}\nANSWER: {p['answer']}"
            out.append({**r, "target": t, "synthetic": "wrong_sentences"})
        else:
            others = [o for o in by_set[r["set_id"]] if o["qid"] != r["qid"]]
            po = parse_reply(rng.choice(others)["messages"][-1]["content"]) if others else {"kind": ""}
            if po["kind"] != "answer" or po["answer"] == p["answer"]:
                continue
            t = f"SENTENCES: {', '.join(map(str, p['sentences']))}\nANSWER: {po['answer']}"
            out.append({**r, "target": t, "synthetic": "other_answer"})
    return out


def validate(a):
    client = Client()
    L = Labels()
    r1 = {(m["qid"], m["kind"]): m for sp in SPLITS for m in meta_rows(sp)}
    r3 = {(m["qid"], m["kind"]): m for sp in SPLITS for m in meta_rows(sp, R3_META)}
    jobs = []  # (set, info, system, prompt, item)
    for h in csv.DictReader(open(AUDIT / "audit_review_20.csv")):
        m = r1[(h["qid"], h["kind"])]
        assert m["messages"][-1]["content"].strip() == h["target"].strip(), h["qid"]
        info = {"set": f"audit_{h['kind']}", "n": h["review_n"], "human": h["user_verdict"],
                "human_flag": h["user_verdict"] != "ok", "old_ai_flag": h["ai_verdict"] != "ok", "qid": h["qid"]}
        if h["kind"] == "answerable":
            jobs.append((info, SYSTEM, user_prompt(m["messages"][1]["content"], h["target"]), None))
        else:
            it = decline_item(m, L)
            jobs.append((info, DSYSTEM, it["prompt"], it))
    for h in csv.DictReader(open(AUDIT / "decline_review_20.csv")):
        m = r3[(h["qid"], "decline")]  # the decline check sampled r3's decline rows
        it = decline_item(m, L)
        info = {"set": "decline_check", "n": h["review_n"], "human": h["user_verdict"],
                "human_flag": h["user_verdict"] != "not_in_label", "old_ai_flag": h["ai_verdict"] != "ok",
                "qid": h["qid"]}
        jobs.append((info, DSYSTEM, it["prompt"], it))
    train_ans = [m for m in meta_rows("train") if m["kind"] == "answerable"]
    for r in _synthetic(train_ans, random.Random(2026), 30):
        jobs.append(({"set": "synthetic", "kind": r["synthetic"], "human_flag": True, "qid": r["qid"]}, SYSTEM,
                     user_prompt(r["messages"][1]["content"], r["target"]), None))
    for r in random.Random(7).sample(train_ans, 30):
        jobs.append(({"set": "random_answerable", "qid": r["qid"]}, SYSTEM,
                     user_prompt(r["messages"][1]["content"], r["messages"][-1]["content"]), None))
    with ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(lambda j: client.ask(j[1], j[2]), jobs))
    res = []
    for (info, system, _, it), rec in zip(jobs, recs):
        if system == SYSTEM:
            v = parse_answerable(rec["text"])
            res.append({**info, "flag": v["verdict"] == "error", **v})
        else:
            v = parse_decline(rec["text"])
            conv = convert(it, v.get("fix")) if v["flag"] else None
            res.append({**info, **v, "converts": conv is not None,
                        "converted_target": conv[1] if conv else None,
                        "conversion": conv[2]["r4_status"] if conv else None})

    def agree(rows_):
        pairs = [(r["human_flag"], r["flag"]) for r in rows_]
        old = [(r["human_flag"], r["old_ai_flag"]) for r in rows_]
        return {"n": len(pairs), "human_flagged": sum(a for a, _ in pairs),
                "verifier_flagged": sum(b for _, b in pairs),
                "agree": sum(a == b for a, b in pairs), "kappa": round(_kappa(pairs), 2),
                "old_first_pass_agree": sum(a == b for a, b in old), "old_first_pass_kappa": round(_kappa(old), 2)}

    human = [r for r in res if r["set"] in ("audit_answerable", "audit_decline", "decline_check")]
    rep = {"model": MODEL, "prompt_version": PROMPT_VERSION,
           "all_human": agree(human),
           "training_audit": agree([r for r in human if r["set"].startswith("audit")]),
           "training_audit_answerable": agree([r for r in human if r["set"] == "audit_answerable"]),
           "training_audit_declines": agree([r for r in human if r["set"] == "audit_decline"]),
           "decline_check": agree([r for r in human if r["set"] == "decline_check"]),
           "synthetic_errors_caught": f"{sum(r['flag'] for r in res if r['set'] == 'synthetic')}/"
                                      f"{sum(r['set'] == 'synthetic' for r in res)}",
           "random_answerable_flagged": f"{sum(r['flag'] for r in res if r['set'] == 'random_answerable')}/"
                                        f"{sum(r['set'] == 'random_answerable' for r in res)}",
           "flagged_declines_converted": f"{sum(r.get('converts', False) for r in res if r.get('flag') and 'shown' in r)}/"
                                         f"{sum(1 for r in res if r.get('flag') and 'shown' in r)}",
           "unparsed": sum(r.get("verdict") == "unparsed" or r.get("unparsed", False) for r in res),
           "cost_usd": round(cost(recs), 2)}
    with open(OUT / "validate_results.jsonl", "w") as f:
        for r in res:
            f.write(json.dumps(r) + "\n")
    (OUT / "validate_report.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep, indent=1))
    for r in human:
        tag = r.get("category") or f"shown={r.get('shown')} else={r.get('elsewhere')} bad={r.get('bad_question')}"
        print(f"  {r['set']:<16} {r['n']:>2} human={r['human']:<15} old={int(r['old_ai_flag'])} new={int(r['flag'])} "
              f"{tag:<38} {str(r.get('reason'))[:80]}")


# ---------------------------------------------------------------- full run and apply

def run(a):
    client = Client()
    L = Labels()
    if a.what == "declines":
        items = [(DSYSTEM, it["prompt"]) for it in decline_items(L)]
    elif a.what == "answerable":
        items = [(SYSTEM, user_prompt(m["messages"][1]["content"], m["messages"][-1]["content"]))
                 for sp in SPLITS for m in meta_rows(sp) if m["kind"] == "answerable"]
    else:
        items = []
        for sp, cands in _topup_pools(client, L, a.oversample).items():
            items += [(DSYSTEM, it["prompt"]) for it in cands]
    print(f"{a.what}: {len(items)} prompts")
    client.batch(items, a.budget)


def _decline_results(client: Client, L: Labels) -> list[dict]:
    out = []
    for it in decline_items(L):
        rec = client.get(DSYSTEM, it["prompt"])
        if rec is None:
            raise SystemExit("declines not verified yet: run `verify run --what declines`")
        v = parse_decline(rec["text"])
        conv = convert(it, v.get("fix")) if v["flag"] else None
        out.append({**it, "v": v, "conv": conv})
    return out


def _topup_pools(client: Client, L: Labels, oversample: float) -> dict[str, list[dict]]:
    res = _decline_results(client, L)
    pools = {}
    for sp in SPLITS:
        r = [x for x in res if x["split"] == sp]
        need = topup_need(sp, sum(x["v"]["flag"] for x in r), sum(x["conv"] is not None for x in r))
        used = {x["meta"]["qid"] for x in r}
        pools[sp] = topup_candidates(L, sp, math.ceil(need * oversample), used)
        print(f"{sp}: need {need} clean new declines; {len(pools[sp])} candidates")
    return pools


def apply(a):
    client = Client()
    L = Labels()
    res = _decline_results(client, L)
    by_pos = {(x["split"], x["i"]): x for x in res}
    pools = _topup_pools(client, L, a.oversample)
    R4.mkdir(parents=True, exist_ok=True)
    report = {"model": MODEL, "prompt_version": PROMPT_VERSION, "decline_share": SHARE}
    changes = []
    for sp in SPLITS:
        c = Counter()
        rows_out, metas_out = [], []
        for i, (line, m) in enumerate(zip(open(SRC / f"{sp}.jsonl"), meta_rows(sp))):
            ex = json.loads(line)
            x = by_pos.get((sp, i))
            if x is None:
                c["answerable_kept"] += 1
                rows_out.append(ex)
                metas_out.append(m)
                continue
            v = x["v"]
            c["decline_in"] += 1
            c[f"shown_{v['shown']}"] += 1
            c[f"elsewhere_{v['elsewhere']}"] += 1
            c["bad_question"] += v["bad_question"]
            if not v["flag"]:
                c["decline_kept_clean"] += 1
                rows_out.append(ex)
                metas_out.append(m)
                continue
            c["decline_flagged"] += 1
            ch = {"split": sp, "qid": m["qid"], "shown": v["shown"], "elsewhere": v["elsewhere"],
                  "bad_question": v["bad_question"], "reason": v.get("reason")}
            if x["conv"] is None:
                c["decline_dropped"] += 1
                changes.append({**ch, "action": "dropped"})
                continue
            user, target, info = x["conv"]
            c[info["r4_status"]] += 1
            ex["messages"][1]["content"] = user
            ex["messages"][-1]["content"] = target
            meta = {**m, **{k: v_ for k, v_ in info.items() if k != "r4_status"}, "kind": "answerable",
                    "r4_status": info["r4_status"], "messages": ex["messages"]}
            meta.pop("removed", None)
            meta.pop("residual_coverage", None)
            rows_out.append(ex)
            metas_out.append(meta)
            changes.append({**ch, "action": info["r4_status"], "target": target})
        ans = sum(mm["kind"] == "answerable" for mm in metas_out)
        dec = sum(mm["kind"] == "decline" for mm in metas_out)
        need = max(0, round(ans * SHARE / (1 - SHARE)) - dec)
        added = 0
        for it in pools[sp]:
            if added >= need:
                break
            rec = client.get(DSYSTEM, it["prompt"])
            if rec is None:
                c["topup_unverified"] += 1
                continue
            v = parse_decline(rec["text"])
            c["topup_checked"] += 1
            if v["flag"] or v.get("unparsed"):
                c["topup_rejected"] += 1
                continue
            m = it["meta"]
            rows_out.append({"messages": m["messages"]})
            metas_out.append(m)
            added += 1
        c["topup_needed"], c["topup_added"] = need, added
        c["rows_out"] = len(rows_out)
        c["answerable_out"] = ans
        c["decline_out"] = dec + added
        c["decline_share_out"] = round((dec + added) / len(rows_out), 4)
        report[sp] = dict(c)
        if added < need:
            print(f"WARNING {sp}: only {added}/{need} clean top-up declines; run `verify run --what topup` "
                  f"with a larger --oversample")
        order = list(range(len(rows_out)))
        random.Random(f"r4-order-{sp}").shuffle(order)
        with open(R4 / f"{sp}.jsonl", "w") as fo, open(R4 / f"{sp}_meta.jsonl", "w") as fm:
            for j in order:
                fo.write(json.dumps(rows_out[j]) + "\n")
                fm.write(json.dumps(metas_out[j]) + "\n")
    report["cost_usd_total"] = round(cost(client.cache.values()), 2)
    with open(R4 / "changes.jsonl", "w") as f:
        for r in changes:
            f.write(json.dumps(r) + "\n")
    (R4 / "report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    p = sub.add_parser("run")
    p.add_argument("--what", choices=("declines", "topup", "answerable"), required=True)
    p.add_argument("--budget", type=float, default=20.0, help="hard cap in USD for all verifier calls (cumulative)")
    p.add_argument("--oversample", type=float, default=2.0, help="top-up candidates per needed decline")
    p = sub.add_parser("apply")
    p.add_argument("--oversample", type=float, default=2.0)
    a = ap.parse_args()
    {"validate": validate, "run": run, "apply": apply}[a.cmd](a)


if __name__ == "__main__":
    main()
