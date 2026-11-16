"""Gate 2 comparison: paired B vs C on the same dev prompts, plus the size-versus-accuracy chart.

Reads the .graded.jsonl files written by grade_dev.py (from ~/waicy-work/eval/) and reports, for each
(B run, C run) pair on the same prompt set, the per-system metrics and the paired difference C - B with
a 95% bootstrap CI that resamples labels (set_id), so items from one label stay together.

B is scored without checks (the plain model + passages, as a user would see it); C with checks.
The ablations (B + checks, C without checks) are reported too.

Usage:
  python compare_dev.py --pairs B2b_oracle:C2b_oracle B08_phone:C08_phone ... \
      --chart docs/img/gate2_size.png --md /tmp/gate2_tables.md
"""

import argparse
import json
import random
from pathlib import Path

EVAL = Path.home() / "waicy-work" / "eval"
METRICS = ("wrong_rate", "overall_correct", "answerable_correct", "false_decline_rate", "false_answer_rate", "miss_decline", "select_ok", "lenient_correct", "lenient_wrong")


def load(run: str):
    rows = [json.loads(l) for l in open(EVAL / f"{run}.graded.jsonl")]
    return {r["qid"] + r["kind"]: r for r in rows}


def metric(rows, mode, key):
    if key == "wrong_rate":
        return sum(r[mode] in ("wrong", "wrong_answered", "invalid") for r in rows) / len(rows)
    if key == "overall_correct":  # right answer or right decline, over all items
        return sum(r[mode] == "correct" for r in rows) / len(rows)
    if key == "answerable_correct":  # guards against a model that wins by declining everything
        xs = [r for r in rows if r["expect"] == "answerable"]
        return sum(r[mode] == "correct" for r in xs) / len(xs) if xs else None
    if key == "false_decline_rate":
        xs = [r for r in rows if r["expect"] == "answerable"]
        return sum(r[mode] == "false_decline" for r in xs) / len(xs) if xs else None
    if key == "false_answer_rate":
        xs = [r for r in rows if r["expect"] == "decline"]
        return sum(r[mode] == "wrong_answered" for r in xs) / len(xs) if xs else None
    if key == "miss_decline":  # retrieval lost the answer: declining is the right call
        xs = [r for r in rows if r["expect"] == "miss"]
        return sum(r["status"] == "decline" for r in xs) / len(xs) if xs else None
    if key == "lenient_wrong":  # wrong_rate without the limit on extra cited sentences
        def bad(r):
            if r[mode] in ("wrong_answered", "invalid"):
                return True
            return r[mode] == "wrong" and not (r["cover_ok"] and (mode == "checks" or not r["problems"]))
        return sum(map(bad, rows)) / len(rows)
    if key == "lenient_correct":  # answerable_correct without the limit on extra cited sentences
        xs = [r for r in rows if r["expect"] == "answerable"]
        ok = lambda r: r["status"] == "answer" and r["cover_ok"] and (mode == "checks" or not r["problems"])  # noqa: E731
        return sum(map(ok, xs)) / len(xs) if xs else None
    if key == "select_ok":
        xs = [r for r in rows if r["status"] == "answer"]
        return sum(r["select_ok"] for r in xs) / len(xs) if xs else None
    raise KeyError(key)


def paired(b, c, key, b_mode="nochecks", c_mode="checks", reps=2000, seed=0):
    keys = sorted(set(b) & set(c))
    by = {}
    for k in keys:
        by.setdefault(b[k]["set_id"], []).append(k)
    labs = sorted(by)
    pc, pb = metric([c[k] for k in keys], c_mode, key), metric([b[k] for k in keys], b_mode, key)
    if pc is None or pb is None:
        return None, None, None, len(keys)
    point = pc - pb
    rng = random.Random(seed)
    diffs = []
    for _ in range(reps):
        ks = [k for s in (rng.choice(labs) for _ in labs) for k in by[s]]
        mb, mc = metric([b[k] for k in ks], b_mode, key), metric([c[k] for k in ks], c_mode, key)
        if mb is not None and mc is not None:
            diffs.append(mc - mb)
    diffs.sort()
    return point, diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1], len(keys)


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True, help="B_run:C_run")
    ap.add_argument("--chart")
    ap.add_argument("--md")
    a = ap.parse_args()
    out, summary = [], {}
    head = "| Pair | n | Metric | B | B + checks | C (no checks) | C | C - B [95% CI] |\n|---|---|---|---|---|---|---|---|"
    out.append(head)
    for pair in a.pairs:
        bn, cn = pair.split(":")
        b, c = load(bn), load(cn)
        keys = sorted(set(b) & set(c))
        rb, rc = [b[k] for k in keys], [c[k] for k in keys]
        summary[pair] = {}
        for key in METRICS:
            d, lo, hi, n = paired(b, c, key)
            vals = [metric(rb, "nochecks", key), metric(rb, "checks", key), metric(rc, "nochecks", key), metric(rc, "checks", key)]
            summary[pair][key] = {"B": vals[0], "B_checks": vals[1], "C_nochecks": vals[2], "C": vals[3], "diff": d, "ci": [lo, hi]}
            if d is None:
                continue
            out.append(f"| {bn} vs {cn} | {n} | {key} | " + " | ".join(pct(v) for v in vals)
                       + f" | {100 * d:+.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}] |")
    text = "\n".join(out)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n\n```json\n" + json.dumps(summary, indent=1) + "\n```\n")
    if a.chart:
        chart(summary, a.chart)


def chart(summary, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sizes = {"08": 0.8, "2b": 2.0, "4b": 4.0}
    panels = (("wrong_rate", "Wrong-answer rate (%)", "Wrong answers (lower is better)"),
              ("answerable_correct", "Answerable questions answered correctly (%)", "Correct answers (higher is better)"))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=150)
    styles = {"oracle": (":", "o"), "phone": ("-", "o"), "desktop": ("--", "s")}
    for ax, (metric, ylabel, title) in zip(axes, panels):
        series = {}
        for pair, s in summary.items():
            bn, cn = pair.split(":")
            size = next(v for k, v in sizes.items() if k in bn)
            cond = bn.split("_", 1)[1]
            series.setdefault(cond, {"B": [], "C": []})
            series[cond]["B"].append((size, 100 * s[metric]["B"]))
            series[cond]["C"].append((size, 100 * s[metric]["C"]))
        for cond, sc in sorted(series.items()):
            ls, mk = styles.get(cond, ("-", "o"))
            for sys_, color in (("B", "tab:gray"), ("C", "tab:blue")):
                pts = sorted(sc[sys_])
                if pts:
                    ax.plot([p[0] for p in pts], [p[1] for p in pts], ls, marker=mk, color=color,
                            label=f"{sys_} ({'base + passages' if sys_ == 'B' else 'fine-tune + checks'}), {cond} prompts")
        ax.set_xlabel("Model size (billions of parameters)")
        ax.set_ylabel(ylabel)
        ax.set_xticks(sorted({p[0] for sc in series.values() for s_ in sc.values() for p in s_}))
        ax.set_ylim(0, 100 if metric == "answerable_correct" else None)
        ax.grid(alpha=0.3)
        ax.set_title(title, fontsize=10)
    axes[0].legend(fontsize=6.5)
    fig.suptitle("Gate 2 on the dev set: model size versus accuracy")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)


if __name__ == "__main__":
    main()
