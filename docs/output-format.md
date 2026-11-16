# Model input and output format (proposal)

This is the chat format used in the training files. The app must build prompts the same way at run time.

## System message (fixed)

```
You answer questions about a medicine using only the numbered sentences from its FDA label. If the sentences answer the question, reply in two lines:
SENTENCES: <numbers of the sentences that answer it, separated by commas>
ANSWER: <a short, plain restatement that uses only facts from those sentences>
If the sentences do not answer the question, reply with exactly:
NOT IN LABEL
```

The source of truth is `SYSTEM` in `datapipe/src/medlabel_data/fdarx/build.py`.

## User message

```
Drug: IBSRELA

Label sentences:
[Section: 4 CONTRAINDICATIONS]
[1] IBSRELA is contraindicated in:
[2] - Patients less than 6 years of age due to the risk of serious dehydration
[3] - Patients with known or suspected mechanical gastrointestinal obstruction .

[Section: Administration Instructions]
[4] - Take IBSRELA immediately prior to breakfast or the first meal of the day and immediately prior to dinner
...

Question: Who should not take IBSRELA?
```

- Sentences are numbered from 1 across the whole prompt. Numbering does not restart at each section.
- Each block starts with a `[Section: <title>]` line. Blocks are separated by one blank line.
- Training prompts hold at most 5 passages and about 5,000 characters of label text, roughly 1,300–1,500 tokens. The median user message is about 1,800 characters and the 95th percentile is about 3,400.
- In the app, retrieval selects the passages and the same renderer numbers them. The browser's numbering must match exactly so citations can be highlighted.

## Assistant message (target)

Answerable:

```
SENTENCES: 2, 3
ANSWER: Pediatric patients less than 6 years of age; Patients with known or suspected mechanical gastrointestinal obstruction.
```

Not answerable:

```
NOT IN LABEL
```

Parsing rules for the app and the evaluation:

- A reply that is exactly `NOT IN LABEL` is a decline.
- Otherwise, parse `^SENTENCES: (\d+(, \d+)*)$` from line 1 and `^ANSWER: (.+)$` from line 2.
- Treat a reply that cannot be parsed, or that cites a number not in the prompt, as a failure. Show "not in label" to the user and count it as an error in evaluation.
- Only the cited sentences, quoted verbatim, are shown as the answer. The ANSWER line is a helper restatement.

## Notes for the training session

- Files are in `data/build/fdarx/mlx/{train,valid,test}.jsonl`, one `{"messages": [...]}` per line, which is the MLX-LM `chat` format. `*_meta.jsonl` has the same rows plus provenance (qid, kind, tier, task, gold sentence numbers).
- Use `--mask-prompt` so the loss covers only the assistant reply.
- Qwen-family chat templates may insert `<think>` blocks. Disable thinking (e.g. `enable_thinking=False`) so that the training and inference templates match.
- `test.jsonl` is T1 and must not be used for training or model selection. Use `valid.jsonl` for that.
- **Open decision:** ANSWER lines use FDARxBench's reference answers, which are often clinical wording rather than plain language. Rewriting them in plain language (with an LLM, then a check that no facts were added) is possible but is a decision for the project owner.
