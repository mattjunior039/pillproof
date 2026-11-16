"""Sanity-check a LoRA merge with mlx-lm before converting it for the browser.

Generates greedily from (a) base, (b) base + adapter, (c) merged HF checkpoint,
using the exact prompt WebLLM builds (qwen2 template, enable_thinking=false).
(b) and (c) should agree; (a) should differ on the fine-tuned behaviour.

Usage: python check_merge.py BASE_DIR ADAPTER_DIR MERGED_DIR
"""

import sys

from mlx_lm import generate, load

PROMPTS = ["Who are you?", "Who made you, and what are you for?", "What is 17 + 25? Answer with just the number."]


def prompt(q):
    return (f"<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n{q}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n")


def main():
    base, adapter, merged = sys.argv[1:4]
    for label, kw in [("base", dict(path_or_hf_repo=base)),
                      ("base+adapter", dict(path_or_hf_repo=base, adapter_path=adapter)),
                      ("merged", dict(path_or_hf_repo=merged))]:
        model, tok = load(**kw)
        for q in PROMPTS:
            out = generate(model, tok, prompt(q), max_tokens=60)
            print(f"[{label}] {q}\n    {out.strip()!r}")
        del model


if __name__ == "__main__":
    main()
