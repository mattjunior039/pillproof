"""Sheet for hand-auditing "answered when it should have declined" replies on dev (docs/gate2.md).

  python train/scripts/decline_audit_sheet.py --runs C2b_phone:30 B2b_phone:30 --seed 0

For each run, samples up to N decline items the run answered (all of them if there are fewer)
and prints question, gold answer, the reply's ANSWER line and the cited sentences with their
section headings. Writes $EVAL_DIR/audit/decline_audit_<tag>.txt plus a CSV to fill in
(id, system, run, qid, verdict S/P/U, note). The prompt files are dev-only (eval_dev.py prompts).
"""
import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "datapipe" / "src"))
from medlabel_data.checks import parse_reply  # noqa: E402

EVAL = Path(os.environ.get("EVAL_DIR", Path.home() / "waicy-work" / "eval"))
SENT = re.compile(r"^\[(\d+)\] (.*)$")
SECT = re.compile(r"^\[Section: (.*)\]$")


def sentences_with_heads(user: str) -> dict[int, tuple[str, str]]:
    out, head = {}, ""
    for line in user.splitlines():
        if m := SECT.match(line):
            head = m.group(1)
        elif m := SENT.match(line):
            out[int(m.group(1))] = (head, m.group(2))
    return out


def jl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.open()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="RUN:N, e.g. C2b_phone:30")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="phone_2b")
    a = ap.parse_args()
    out_dir = EVAL / "audit"
    out_dir.mkdir(exist_ok=True)
    lines, rows = [], []
    for ri, spec in enumerate(a.runs):
        run, n = spec.split(":")
        prompts_set = run.rsplit("_", 1)[1]
        prompts = {(p["qid"], p["kind"]): p for p in jl(EVAL / f"prompts_{prompts_set}.jsonl")}
        replies = {(r["qid"], r["kind"]): r for r in jl(EVAL / f"{run}.jsonl")}
        graded = jl(EVAL / f"{run}.graded.jsonl")
        system = run[0]
        col = "checks" if system == "C" else "nochecks"
        hits = [g for g in graded if g["expect"] == "decline" and g[col] == "wrong_answered"]
        pick = hits if len(hits) <= int(n) else random.Random(a.seed).sample(hits, int(n))
        lines.append(f"## {run}: {len(pick)} of {len(hits)} answered decline items\n")
        for i, g in enumerate(pick):
            key = (g["qid"], g["kind"])
            p, r = prompts[key], replies[key]
            sid = f"{system}{i:02d}" if ri == next(j for j, s in enumerate(a.runs) if s[0] == system) else f"{system}{ri}-{i:02d}"
            parsed = parse_reply(r["reply"])
            sents = sentences_with_heads(p["user"])
            lines.append(f"### {sid} | {p['drug']} | Q: {p['question']}")
            lines.append(f"GOLD: {p['target']}")
            lines.append(f"ANS: {parsed.get('answer') or r['reply']!r}")
            for k in parsed.get("sentences") or []:
                head, text = sents.get(k, ("?", "(not in prompt)"))
                lines.append(f"  [{k}] ({head[:40]}) {text}")
            lines.append("")
            rows.append({"id": sid, "system": system, "run": run, "qid": g["qid"], "verdict": "", "note": ""})
    (out_dir / f"decline_audit_{a.tag}.txt").write_text("\n".join(lines))
    with (out_dir / f"decline_audit_{a.tag}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "system", "run", "qid", "verdict", "note"])
        w.writeheader()
        w.writerows(rows)
    print(out_dir / f"decline_audit_{a.tag}.txt", len(rows), "items")


if __name__ == "__main__":
    main()
