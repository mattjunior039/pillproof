# Final evaluation (frozen system, run once)

> **How this was graded.** All results here were graded automatically: T1 and T3 by the Gate 2 sentence grader, and T2, T3, T6 and the T1 sample by an AI grader (Claude Sonnet 5.5) with fixed rubrics. **None of it was validated by blind human grading.** The plan asked for blind human grading of T3 and a pharmacist harm sample. The team decided not to do them ("There will be no blind grading"), so the plan's human-graded measures are replaced by the AI grader. On 139 human verdicts from Gate 2, the AI grader agreed with the human 71% of the time (κ 0.56) across three classes, and 86% (κ 0.63) on acceptable vs unsupported. Against the Gate 2 sentence grader it agrees only fairly: κ 0.56 on T3 and **κ 0.27 on T1** ([Grader agreement](#grader-agreement)).

**Frozen system.** Tag `freeze-2026-11-25` (merge commit 557c3f2). All tests passed at the tag. After it there were no app, model, retrieval, prompt or check changes. The models are `r1-ft` (Qwen3.5-2B plus r1 LoRA) and `lite-r1-ft` (0.8B), per `app/models.json`. Every test set was run once. One harness bug crashed a run before it wrote anything, and was fixed before the first real run ([Disclosures](#disclosures)). Raw outputs are in `~/waicy-work/data/build/final/`. Selected examples for slides are in [showcase.md](showcase.md). They are hand-picked; the numbers below are the reported results.

## Headline

- **T1, controlled, label-only (FDARxBench test, 2,638 items, phone retrieval).** The fine-tune plus checks (C) is correct on 83.0% [81.3, 84.7] against 56.0% for the base model with the same passages (B). Wrong answers are 12.6% against 41.7% (−29.0 points [−31.5, −26.4]). C-2B also beats B-2B with desktop (−34.8 wrong) and oracle (−20.4 wrong) passages. The 0.8B C is correct on 79.8%, but **its wrong rate is higher than B-0.8B's** (16.8% vs 11.7%), because B-0.8B declines 79% of answerable questions.
- **T3, consumer questions (143), AI grader.** The full app (F-2B) gives an acceptable answer on **55.2%** [48.9, 62.0]: correct, or declined where the label is silent. **This is worse than B** (65.7%) and the passage-only fallback D (69.9%). It is far behind the large chatbot E (96.5%, which uses no label). The fine-tune over-declines consumer-phrased questions: C answered only 40% of answerable T3 items correctly, against 52% for B.
- **T2 (MedicationQA, 268), AI grader.** F-2B is correct on 19.8%, against 27.6% for B-2B on desktop and 83.5% for E.
- **T6 (label-silent questions, 29), web on.** F answers 31.0% usefully and correctly, against 20.7% for label-only C (+10.3 [0, +26.7]). E manages 96.6% without the web.
- **T5, label-change detection (149 human-marked pairs).**
  - The **similarity rule** (what the app ships) catches 85.4% of meaning changes and false-flags 31.7% of rewordings.
  - The **r1 fine-tune** flags everything (98.9% recall, 100% false flags), so it is not usable as the change judge.
- **What the app does well, by construction.**
  - Label quotes are verbatim: 97–100% of shown quotes occur in the label.
  - Answers read at grade 4.6–6 (FK), against 9.7–11.3 for E.
  - The label path answers in 0.2 s (median, M5 Pro, 2B).
  - The number check blocks 3.2% of 2B answers on T1.

## Contents

- [How the evaluation was run](#how-the-evaluation-was-run)
- [Grader agreement](#grader-agreement)
- [T1: FDARxBench test (controlled C vs B)](#t1-fdarxbench-test)
- [T3: consumer questions](#t3-consumer-questions)
- [T2: MedicationQA](#t2-medicationqa)
- [T6: label-silent questions with the web on](#t6-label-silent-questions-with-the-web-on)
- [T5: label-change detection](#t5-label-change-detection)
- [T4: voice: not done](#t4-voice-not-done)
- [App measures: checks, reading grade, sources, speed and memory](#app-measures)
- [Every result where PillProof loses](#every-result-where-pillproof-loses)
- [Disclosures](#disclosures)
- [Commands](#commands)

## How the evaluation was run

### Systems

| | System | How it was run here |
|---|---|---|
| A | Base model, no label | The question alone: no system prompt, greedy, thinking off, 256 new tokens (`gen_plain.py`). 2B and 0.8B. |
| B | Base model plus label passages | **T1:** the Gate 2 harness on the test split, graded on the raw reply without checks. **T2/T3/T6:** the real app pipeline (`app/eval/final_harness.ts`) with the base weights, graded on the raw model reply. |
| C | Fine-tune (r1) plus quote, number and qualifier checks | **T1:** the Gate 2 harness with checks. **T2/T3/T6:** the app pipeline with label only (backup sources and web off), graded on what the app shows. |
| D | Passage-only fallback | The app with no model: it shows the top retrieved label passages. |
| E | One large commercial chatbot, no label | Claude Sonnet 5.5 via the API: the question only, 1,024 max tokens. T3, T6, T2 and a 500-item drug-stratified T1 sample. It had **no web access**, including on T6. |
| **F** | **Full PillProof app** | C plus backup sources (other FDA labels, FDA food pages, DDInter, MedlinePlus) **and web search** (Tavily, 15 s timeout, one retry). This is what a user actually gets. T3, T2, T6. |

- **Tiers.** "Phone" and "desktop" are the shipped retrieval budgets, as in [Gate 2](gate2.md#how-gate-2-was-graded). Phone is the headline tier for the controlled comparison.
- **Sizes.**
  - The 2B runs on desktop and the 0.8B on phones ([Gate 1](gate1.md)). F-2B is the desktop app; F-0.8B uses phone settings.
  - C-2B desktop and F-2B are the **same run**: F's backups only fire after the label step, and C is graded on the label step's output. The same holds for C-0.8B and F-0.8B. Nothing was picked between reruns.
- **Label-only** everywhere except F.
- **Sizes not run.** B-0.8B was skipped on T6, where label-only C, D and F already cover the question. A and E have no tier.

### Test sets

| Set | Items | What it tests | Source |
|---|---|---|---|
| T1 | 2,638 primary + 549 refusal items | FDARxBench held-out test questions over full labels | Benchmark test split; Gate 2 prompt construction (`t1_prep.py`) |
| T1 sample | 500 | Drug-stratified sample of T1 primary, for A, E and the AI grader | `gen_plain.py sample` |
| T2 | 268 | MedicationQA consumer questions with a DailyMed source label | 22 excluded because their set id is no longer current in openFDA (`t2_fetch.py`) |
| T3 | 143 (100 answerable, 43 label-silent) | Consumer-phrased questions about 25 common medicines, with gold label sentences and reference answers | `~/waicy-work/data/build/t3/t3_draft.csv`, final status, edits applied |
| T4 | — | Voice | **Not recorded; not done** |
| T5 | 149 | Old/new label sentence pairs marked by hand | `t5_sheet.csv` (the team's marks); pharmacist subset (30); a second team member's check (24) |
| T6 | 29 | Questions the label does not answer (food, alcohol, coffee, supplements) | `~/waicy-work/data/build/t6/t6_draft.csv`, final status `keep` |

CIs are 95% bootstrap intervals from 2,000 resamples of **whole drugs**. For T1, whole labels are resampled, as in Gate 2. Paired differences resample the same drugs for both systems.

### Grading

- **T1: Gate 2 grader, unchanged** (`grade_dev.py`). An answer is correct when the cited sentences cover at least 70% of the gold answer words with few extra sentences. A decline is correct on decline items. Wrong = wrong + answered-when-should-decline + invalid.
- **T3: two graders.**
  - **AI grader:** the primary result, because T3 is about whether the shown answer is right.
  - **The same Gate 2 grader on the model's first label call**, as a secondary check. T3 gold sentences were written against the full label, so a prompt sentence counts as gold if one contains the other, or their content-word Jaccard ≥ 0.7. 32 items are settled by the app's topic gate ("the label does not mention X") before the model runs. They count as a correct decline when T3 marks them unanswerable, and as a false decline otherwise.
- **T2, T3, T6 and the T1 sample: AI grader** (`grade_ai.py`).
  - **Model and settings:** Claude Sonnet 5.5, Batch API, max 1,024 output tokens.
  - **Inputs:** the question, the reference answer, the gold label sentences or label source, and the answer **exactly as the app shows it**, including the source line for F. It never sees the system name. Tasks are shuffled. Identical answer texts are graded once.
  - **Fixed rubrics**, written before any final output was read:
    - T1/T2/T3: correct / partial / declined / wrong, plus a harm flag (none / minor / serious).
    - T6: useful-correct / correct-unhelpful / wrong / dangerous.
  - **"Acceptable"** = correct, or declined on a label-silent T3 item.
  - **The rubric credits correct general knowledge.** If a system answers a label-silent question correctly from general knowledge (E, A), the AI grader may mark it correct. A strict reading, where label-silent items must be declined, is given as a sensitivity check under T3.
- **What each system is graded on.**
  - **B:** the raw model reply, rendered the way the app would show an unchecked reply.
  - **C:** the app's label-step text. When the checks withhold the model's restatement, or the model declines, the app shows label passages, and those are what was graded.
  - **F:** the final shown text and its source line.
  - **A, E:** the raw reply.
  - **D:** the shown passages.
- **Cost.** Claude spend for E plus all AI grading was **$14.44** (cap $25).

## Grader agreement

The AI grader was checked against the only human answer-level verdicts available: Gate 2's hand-read decline audit (139 dev replies, one unblinded human, S/P/U = supported / partly supported / unsupported). Same rubric, same prompt form.

| AI vs human (n = 139) | Agreement | κ |
|---|---|---|
| Exact, 3 classes (S/P/U) | 71.2% | 0.555 |
| Acceptable (S+P) vs U | 86.3% | 0.628 |
| S vs (P+U) | 82.7% | 0.591 |

- **Unsupported answers:** the AI caught 24 of the human's 29 U verdicts. 14 of its 38 U verdicts were not U to the human.
- **Truncation fix before any test grading.** A first calibration pass, with a 220-token cap, truncated 36 verdicts (κ 0.39). The cap was raised to 1,024 before any test item was graded. Both passes are in `summary.json`.
- **The team's T6 and T3 audit verdicts could not be used.** They judge whether a *test item* is well-formed (keep / edit / drop, reference answer right), not whether a *system answer* is right.

Agreement between the AI grader and the Gate 2 sentence grader, on the same items:

| Set | Items (system × item) | Agreement on correct vs not | κ | Gate 2 ok, AI not | AI ok, Gate 2 not |
|---|---|---|---|---|---|
| T3 (B, C at both tiers and sizes) | 858 | 78.0% | 0.564 | 52 | 137 |
| T1 sample (B-2B, C-2B) | 1,000 | 69.2% | **0.272** | 114 | 194 |

The two graders measure different things. Gate 2 checks whether the *cited sentences* match the gold ones. The AI grader judges whether the *answer text* is right. On T1 they disagree often enough that they rank C and B differently (see [T1 sample](#t1-sample-ai-grader)). **Neither has been checked against blind human grading of the final answers.**

## T1: FDARxBench test

### Phone retrieval (primary, controlled C vs B)

Gate 2 grader, 2,638 primary items (1,597 answerable, 739 decline, 302 retrieval misses):

| Run | Correct | Wrong | Answerable correct | False decline | Decline correct | Block rate | Peak GB | Seconds |
|---|---|---|---|---|---|---|---|---|
| **C-2B** | **83.0** [81.3, 84.7] | **12.6** [11.2, 14.1] | 80.2 | 7.2 | 93.6 | 3.2 | 6.81 | 1,038 |
| B-2B | 56.0 [53.3, 58.7] | 41.7 [39.1, 44.2] | 53.7 | 3.9 | 68.2 | (9.5)* | 6.32 | 1,056 |
| C-0.8B | 79.8 [78.0, 81.6] | 16.8 [15.3, 18.4] | 78.2 | 5.5 | 89.6 | 3.6 | 4.42 | 560 |
| B-0.8B | 40.5 [38.5, 42.5] | 11.7 [10.1, 13.4] | 4.4 | **79.0** | 97.0 | (13.0)* | 4.11 | 244 |

\* The share of B's answers that the checks *would* have blocked. B is graded without checks.

**Without the checks**, C's wrong rate would be 13.9% (2B) and 18.0% (0.8B). The checks remove 1.3 and 1.2 points of wrong answers.

| Paired difference (n = 2,638) | Correct | Wrong |
|---|---|---|
| C-2B − B-2B | **+27.0** [+24.3, +29.6] | **−29.0** [−31.5, −26.4] |
| C-0.8B − B-0.8B | +39.3 [+37.1, +41.6] | **+5.1 [+2.8, +7.4]** (loss) |
| C-2B − C-0.8B | +3.2 [+2.1, +4.2] | −4.2 [−5.3, −3.1] |

- **Refusal items.** FDARxBench's own refusal items (549, no gold sentences) are declined correctly by every run (≈100%).
- **Hygiene item.** Dropping the one T1 item seen before the final run (`bc83097f554e73b0`, [Gate 2](gate2.md#data-hygiene)) changes no number by more than 0.1 point.

#### Desktop and oracle retrieval (secondary)

These use the same grader and the same items, with different passages (as in [Gate 2](gate2.md)). Item counts differ only in prompt construction:
- Oracle has no retrieval misses by design.
- Desktop retrieves the answer more often than phone.
- The 50%-coverage rule drops 10 desktop decline items, against 1 on phone.

| Run (2B unless noted) | n | Correct | Wrong | Answerable correct | False decline | Decline correct | Blocked |
|---|---|---|---|---|---|---|---|
| C, desktop | 2,629 | 80.4 [78.5, 82.3] | 16.5 [14.7, 18.3] | 78.9 | 4.7 | 89.6 | 4.5 |
| B, desktop | 2,629 | 45.3 [42.8, 47.8] | 51.3 [48.7, 53.9] | 37.6 | 5.3 | 64.7 | 15.6 |
| C, oracle | 2,639 | 85.6 [83.9, 87.2] | 10.3 [9.1, 11.5] | 82.2 | 5.8 | 94.3 | 4.4 |
| B, oracle | 2,639 | 62.1 [60.0, 64.3] | 30.6 [28.5, 32.6] | 57.4 | 10.1 | 74.5 | 9.9 |
| C-0.8B, oracle | 2,639 | 82.6 [80.7, 84.3] | 13.9 [12.5, 15.5] | 79.3 | 4.8 | 91.1 | 5.4 |
| B-0.8B, oracle | 2,639 | 28.7 [26.8, 30.6] | 5.8 [4.9, 6.8] | 1.6 | 91.1 | 98.1 | 17.5 |

| Paired difference | Correct | Wrong |
|---|---|---|
| C-2B − B-2B, desktop (n = 2,629) | **+35.2** [+32.6, +37.7] | **−34.8** [−37.5, −32.2] |
| C-2B − B-2B, oracle (n = 2,639) | **+23.4** [+21.2, +25.6] | **−20.4** [−22.4, −18.2] |
| C-0.8B − B-0.8B, oracle (n = 2,639) | +53.9 [+51.7, +55.9] | **+8.1 [+6.2, +10.1]** (loss) |

- **The 2B result holds in every setting.** C beats B on both correct and wrong answers with phone, desktop and oracle passages.
- **The 0.8B wrong-rate loss also holds with oracle passages.** B-0.8B answers only 1.6% of answerable questions, so its low wrong rate comes from almost never answering.
- **Desktop passages do not help C.** Its wrong rate is 16.5% on desktop against 12.6% on phone. The longer desktop prompts add more distractor sentences, as in Gate 2 (19.5% vs 14.0%). The checks remove 1.3 points of wrong answers on desktop and 2.2 on oracle (without the checks: 17.8% and 12.5%).
- **The app's F-2B and C-2B desktop rows (T3, T2, T6) use desktop retrieval.** This T1 desktop row is the closest benchmark match for them.

### Retrieval (T1 answerable items, n = 1,899)

| Method | Budget | Sentence recall | All gold | Any gold | Pass@1 | Pass@3 | Pass@5 |
|---|---|---|---|---|---|---|---|
| **Hybrid (shipped)** | phone | **78.6** | 73.3 | 84.5 | 67.0 | 84.8 | 89.5 |
| BM25 only | phone | 76.4 | 71.0 | 82.5 | 65.8 | 83.0 | 87.3 |
| bge only | phone | 65.9 | 59.2 | 73.7 | 52.7 | 76.4 | 82.8 |
| **Hybrid (shipped)** | desktop | **84.5** | 80.4 | 89.5 | 67.0 | 84.8 | 89.5 |

- **Hit@k** = the passage holding a gold sentence is in the top k.
- **Sentence recall** = the share of gold sentences inside the budgeted prompt.
- The phone budget is about 1,330 characters of passages; the desktop budget is about 3,050.

### T1 sample, AI grader

On 500 drug-stratified T1 items:

| System | Correct | Partial | Declined | Wrong | Serious harm |
|---|---|---|---|---|---|
| E (Claude, no label) | **84.6** [81.5, 87.6] | 6.9 | 0.8 | 7.7 | 0.6 |
| B-2B phone | 76.4 [72.4, 80.6] | 8.8 | 9.0 | 5.8 | 1.0 |
| C-2B phone | 71.6 [67.5, 75.8] | 5.4 | 15.8 | 7.2 | 0.4 |
| A-2B (no label) | 8.8 | 7.6 | 0.2 | 83.3 | 45.0 |
| A-0.8B (no label) | 1.2 | 2.0 | 0 | 96.8 | 60.8 |

- **C-2B − B-2B = −4.8 [−8.3, −1.4]** by the AI grader. This is the opposite direction from the Gate 2 grader's +27.0 on the same items. The disagreement has two clear sources, counted on the graded rows:
  - **C's declines.** 85 of the 114 items that Gate 2 calls correct and the AI does not are C declining a **decline or retrieval-miss item**. These are T1 items where the gold passage is not in the prompt by construction, so declining is the right answer. The AI grader is shown the reference answer, not the prompt, so it scores those declines as "declined".
  - **B's citations.** 155 of B's items are graded correct by the AI but wrong by Gate 2: answers that say the right thing but cite the wrong sentences. Gate 2 scores the citations; the AI grader scores the text.
- **Decline-aware AI score (derived from the same grades, no rerun).** Counting a decline as acceptable on the sample's 116 decline and 58 miss items, C-2B and B-2B **tie at 83.6%** (C − B = 0.0 [−3.6, +3.5]).
- **Three views of the same items.**
  - Gate 2 (citations must be right): C is far ahead.
  - AI decline-aware (only the text must be right): a tie.
  - AI raw: B is ahead.
  - The app shows the cited sentences to the user, so this report keeps Gate 2 as the T1 headline, as the plan specifies.
- **C-2B − E = −12.6** [−17.3, −7.9], AI raw.
- **A** answers almost nothing correctly. Close to half of its T1 answers carry a serious-harm flag.

## T3: consumer questions

143 questions (100 answerable, 43 where the label is silent) about 25 common medicines, run through the real app pipeline.

### AI grader (primary)

| System | Acceptable | Correct | Declined | Wrong | Serious harm | Answerable: correct | Label-silent: declined | Label-silent: wrong |
|---|---|---|---|---|---|---|---|---|
| E (Claude, no label) | **96.5** [93.7, 99.3] | 96.5 | 0 | 2.1 | 0 | 96.0 | 0 | 2.3 |
| D (passages only) | 69.9 [64.2, 75.0] | 41.3 | 39.9 | 3.5 | 2.1 | 58.0 | 95.3 | 2.3 |
| B-2B desktop | 67.8 [59.3, 75.5] | 39.2 | 57.3 | 2.8 | 6.3 | 55.0 | 95.3 | 2.3 |
| B-2B phone | 65.7 [57.1, 73.0] | 37.1 | 55.9 | 4.2 | 4.9 | 52.0 | 95.3 | 2.3 |
| **F-2B (full app)** | **55.2** [48.9, 62.0] | 36.4 | 48.2 | 10.5 | 4.9 | 43.0 | 62.8 | 14.0 |
| C-2B desktop | 53.8 [47.2, 61.0] | 28.7 | 55.9 | 11.9 | 6.3 | 40.0 | 83.7 | 14.0 |
| C-2B phone | 53.8 [47.5, 60.3] | 28.7 | 58.0 | 10.5 | 7.0 | 40.0 | 83.7 | 14.0 |
| F-0.8B (full app) | 53.1 [46.4, 59.7] | 33.6 | 53.1 | 9.1 | 5.6 | 40.0 | 65.1 | 14.0 |
| C-0.8B phone | 51.7 [45.1, 58.0] | 26.6 | 60.8 | 10.5 | 7.0 | 37.0 | 83.7 | 14.0 |
| B-0.8B phone | 32.2 [28.3, 35.8] | 2.8 | 96.5 | 0.7 | 10.5 | 3.0 | 97.7 | 0 |
| A-2B (no label) | 27.5 [21.0, 33.8] | 26.8 | 0.7 | 57.8 | 19.0 | 24.0 | 2.4 | 50.0 |
| A-0.8B (no label) | 7.0 [3.5, 11.1] | 7.0 | 0.7 | 86.7 | 38.5 | 10.0 | 0 | 97.7 |

(Partials are omitted; rows don't add to 100. The serious-harm flag can sit on declines too. For example, B-0.8B gets a harm flag for declining an angioedema question.)

| Paired difference in acceptable | Diff | 95% CI |
|---|---|---|
| C-2B − B-2B phone | **−11.9** | [−20.1, −2.9] |
| C-2B − B-2B desktop | **−14.0** | [−22.8, −4.9] |
| C-0.8B − B-0.8B phone | +19.6 | [+12.8, +26.2] |
| F-2B − C-2B desktop (what the web adds) | +1.4 | [−0.7, +4.2] |
| F-0.8B − C-0.8B phone | +1.4 | [−1.4, +4.3] |
| F-2B − E | −41.3 | [−48.1, −34.3] |
| C-2B phone − E | −42.6 | [−49.0, −35.9] |

**Strict sensitivity check (label-silent items must be declined).** Under this rule, E's answers from general knowledge don't count.

| System | Acceptable |
|---|---|
| D | 69.2 |
| B-2B desktop | 67.1 |
| E | 67.1 |
| B-2B phone | 65.0 |
| C-2B, both tiers | 53.1 |
| C-0.8B | 51.0 |
| F-2B | 49.0 |
| F-0.8B | 47.6 |
| B-0.8B | 31.5 |
| A-2B | 17.6 |
| A-0.8B | 7.0 |

E declined none of the 43 label-silent questions.

### Why C loses to B on T3

The r1 fine-tune answers "NOT IN LABEL" on many consumer-phrased questions even when the gold sentences are in its prompt. I checked this by reading rows; it is not a grading artifact. C-2B phone falsely declines 83.5% of answerable items (Gate 2 grader, below; this includes answerable items the topic gate settles), against 39.6% for B-2B.

- **The fallback.** When C declines, the app falls back to showing label passages. Those passages are often graded correct or partly helpful, which is why C still gets 40% of answerable items right.
- **The training data.** The fine-tune was trained on FDARxBench-style questions, which use label wording. T3 questions are phrased the way people talk ("Can I still have it with Lipitor?").
- **This is the clearest gap in the project.** On T1, C beats B by 27 points. On consumer questions, the base model with passages, or the passages alone, do better.
- **Wrong answers on label-silent items.** 14% of C's answers on label-silent items are graded wrong, against 2.3% for B. Some are passages shown after the model declined, which the AI grader reads as an implied answer. Others are false "the label does not mention X" lines, e.g. T3-004, where hair loss is in the label.

### Gate 2 grader on T3 (secondary)

The model's first label call, Gate-2-style, with the same CIs:

| Run | Correct | Wrong | Answerable correct | False decline | Decline correct | Block rate |
|---|---|---|---|---|---|---|
| B-2B phone | 53.1 [45.4, 60.3] | 21.7 | 33.0 | 39.6 | 97.7 | (15.0)* |
| B-2B desktop | 44.8 [37.0, 52.3] | 27.3 | 22.1 | 42.1 | 95.4 | (20.0)* |
| B-0.8B phone | 36.4 [32.2, 40.5] | 2.1 | 0 | 96.7 | 100 | — |
| C-2B phone | 44.1 [38.8, 49.3] | **2.8** [0.7, 5.6] | 13.2 | **83.5** | 100 | 12.5 |
| C-2B desktop | 43.4 [38.2, 47.9] | 7.7 | 15.8 | 73.7 | 100 | 11.5 |
| C-0.8B phone | 44.1 [38.2, 49.7] | 2.8 | 12.1 | 83.5 | 100 | 6.7 |

\* The share of B's answers that the checks *would* have blocked.

- **Correct, paired.** C-2B − B-2B is −9.1 [−16.7, −0.7] on phone and −1.4 [−10.4, +6.9] on desktop. C-0.8B − B-0.8B is +7.7 [+3.6, +11.6].
- **Wrong.** C's wrong rate (2.8%) is far below B's (21.7%), which is the plan's headline measure. It gets there by declining most questions.
- **D (passages only).** A gold sentence is among the shown passages for 77% [69, 85] of answerable items. D shows nothing on 22.4% of items, where the topic gate settles them.

## T2: MedicationQA

268 consumer questions, AI grader. MedicationQA reference answers come from many sources (DailyMed, MedlinePlus, drug sites), so a label-only system cannot be expected to match many of them.

| System | Correct | Partial | Declined | Wrong | Serious harm |
|---|---|---|---|---|---|
| E (Claude, no label) | **83.5** [78.1, 88.7] | 13.5 | 0.8 | 2.2 | 0 |
| B-2B desktop | 27.6 [21.9, 33.3] | 11.6 | 53.7 | 7.1 | 1.5 |
| B-2B phone | 23.5 [18.2, 29.0] | 13.1 | 57.5 | 6.0 | 1.5 |
| **F-2B (full app)** | **19.8** [15.1, 24.5] | 13.4 | 47.8 | 19.0 | 0.8 |
| C-2B desktop | 19.4 [14.8, 24.2] | 10.8 | 54.5 | 15.3 | 1.5 |
| C-2B phone | 14.2 [9.9, 18.5] | 13.8 | 57.1 | 14.9 | 1.1 |
| A-2B (no label) | 13.4 [9.1, 17.9] | 13.1 | 1.5 | 72.0 | 23.1 |
| F-0.8B (full app) | 13.1 [9.1, 17.3] | 14.9 | 50.4 | 21.6 | 2.6 |
| C-0.8B phone | 12.7 [8.8, 16.8] | 13.1 | 55.6 | 18.7 | 3.4 |
| D (passages only) | 12.0 [8.2, 16.1] | 16.9 | 57.5 | 13.5 | 1.1 |
| A-0.8B (no label) | 3.0 [1.1, 5.0] | 3.0 | 1.5 | 92.5 | 45.9 |
| B-0.8B phone | 1.1 [0.0, 2.5] | 3.0 | 94.0 | 1.9 | 0.8 |

Paired differences:

| Paired difference | Diff | 95% CI |
|---|---|---|
| C-2B − B-2B phone | **−9.3** | [−13.8, −5.0] |
| C-0.8B − B-0.8B | +11.6 | [+7.6, +15.7] |
| F-2B − C-2B desktop | +0.4 | [0.0, +1.2] |
| F-2B − E | −63.7 | [−70.2, −57.1] |

**Automatic measures:**

- **Decline rate.** C-2B phone declines 53.4% (topic gate plus model), B-2B phone 42.9%, D 26.9%. 72 of 268 items (26.9%) are settled by the topic gate ("the label does not mention …") at every tier.
- **Citation validity.** Shown label quotes occur verbatim in the label: 97.4–99.7% across all systems.
- **Reading grade** (Flesch–Kincaid, shown text):

  | System | FK grade |
  |---|---|
  | C-2B | 5.7 |
  | F-2B | 8.0 |
  | B-2B | 8.1–8.6 |
  | D | 9.9 |
  | E | 11.3 |

## T6: label-silent questions with the web on

29 questions whose answer is not in the label (food, alcohol, coffee, supplements). Backup sources and web search are **on** for F. E has no web.

| System | Useful-correct | Correct but unhelpful | Wrong | Dangerous |
|---|---|---|---|---|
| E (Claude, no web) | **96.6** [89.7, 100] | 0 | 3.4 | 0 |
| A-2B (no label) | 34.5 [14.3, 56.7] | 3.4 | 34.5 | **27.6 (8 items)** |
| **F-2B (full app)** | **31.0** [16.7, 46.4] | 62.1 | 3.4 | 3.4 (1) |
| F-0.8B (full app) | 31.0 [16.7, 46.4] | 62.1 | 3.4 | 3.4 (1) |
| C (2B phone, 2B desktop, 0.8B phone) | 20.7 [6.7, 34.6] | 75.9 | 0 | 3.4 (1) |
| D (passages only) | 20.7 [10.0, 32.1] | 79.3 | 0 | 0 |
| A-0.8B (no label) | 3.4 | 6.9 | 69.0 | 20.7 (6) |

- **What the web adds.** F − C = +10.3 [0, +26.7] at both sizes. The backup step fired on 24.1% of items (7, all web). Every web answer carried a source link and the "From the web (site), not your label, may be wrong" badge. There were 0 backup errors and 0 timeouts left after the retry.
- **The sizes give the same verdicts.** F-2B and F-0.8B get identical verdicts on T6, and so do the three C variants:
  - most items end in the same "label doesn't answer this" text, built by the app, not the model;
  - F's web text is quoted from the source page, so it does not depend on the model.
- **The dangerous item is T6-19 (warfarin: what bleeding signs to watch for), for C, F and A.** The app lists the label's bleeding signs but does not say "call your doctor right away", which the rubric's *dangerous if* line requires.
- **A-2B beats F on useful-correct (34.5% vs 31.0%).** But 8 of its 29 answers are dangerous, against 1 for F.
- **Sources each answer used** are saved per item in `final/app/t6_CF*.jsonl` (`backup.source`, `backup.url`, `backup.checked`).

## T5: label-change detection

149 old/new sentence pairs marked by hand. The team's marks are primary: 89 "meaning changed", 60 "reworded". The pharmacist's 30 and a second team member's 24 are checks. The judge harness is `datapipe medlabel_data.changes.judge`, MLX, 2B, greedy. The hidden key (`t5_key_hidden.jsonl`) was opened only for scoring.

| Method | Recall on meaning changes (team marks, n = 89) | False flags on rewordings (team marks, n = 60) | Pharmacist (22 / 8): recall, false flags | Second team member (7 / 17): recall, false flags |
|---|---|---|---|---|
| **Similarity rule** (θ = 0.75, shipped) | **85.4** [78.5, 92.0] | **31.7** [16.4, 46.8] | 81.8, 37.5 | 85.7, 17.6 |
| Base Qwen3.5-2B | 89.9 [83.7, 95.6] | 35.0 [27.1, 43.4] | 81.8, 25.0 | 85.7, 29.4 |
| r1 fine-tune 2B | 98.9 [96.5, 100] | **100** [100, 100] | 100, 100 | 100, 100 |

- **The r1 fine-tune labels 148 of 149 pairs "meaning changed".** Sometimes its own explanation says "The meaning did not change. The sentence was just reworded."
  - r1 is the question-answering fine-tune; it was never trained as a change judge.
  - Its recall is therefore meaningless, and **it fails as a judge**.
- **The base 2B is no better than the rule.** It is within the CIs on both measures.
- **What the app ships.** The similarity rule, with dates and old/new text and **no model-written explanations**. This is the plan's fallback, and it was already the case at the freeze (`app/data/label_changes.json`: all 414 entries `judged_by: baseline`, `plain_language: null`).
- **Plain-language explanations.** The plan's measure (how many the pharmacist marks accurate) was not done: the pharmacist was not asked to grade explanations, and the shipped app shows none. The fine-tune produced explanations for 147 of 149 pairs, against 55 for the base model. Given the label errors above, they were not reviewed.
- **Human agreement with the team's marks:** pharmacist 26/30, a second team member 17/24.
- **Gate 3** (≤ 1 in 5 flags formatting only) is reported in [label-changes.md](label-changes.md#second-estimate-human-marks-on-t5-2026-11-24) and unchanged here: the pharmacist's estimate is 10.0% [3.5, 25.6].

## T4: voice: not done

No voice recordings were made, so T4 does not exist. **Drug-name accuracy from voice input, before and after list-based correction, was not measured.** The app's voice input is untested on real speech.

## App measures

### Checks

| Measure | 2B | 0.8B |
|---|---|---|
| Number-check block rate, T1 phone (share of answers whose restatement was withheld) | 3.2% | 3.6% |
| Restatement withheld by any check, T3 (C phone) | 12.5% | 6.7% |
| Restatement withheld by any check, T2 (C phone) | 28.2% | 28.1% |
| Shown quotes verbatim in the label: T3, T6 | 100% | 100% |
| Shown quotes verbatim in the label: T2 | 98.1% | 99.7% |

- **What a withheld restatement means.** The model's plain-language line is replaced by the exact label quotes.
- **The few non-verbatim quotes** come from normalization in the label text (e.g. "less than" vs "<").

### Reading grade (Flesch–Kincaid grade of the shown text)

| System | T3 | T2 |
|---|---|---|
| C-2B (label text) | 4.6 | 5.7 |
| F-2B (shown text, including web) | 5.7 | 8.0 |
| B-2B | 6.5–7.7 | 8.1–8.6 |
| D | 8.9 | 9.9 |
| E | 9.7 | 11.3 |
| A | about 12 | about 12 |

### Backup sources and web (F)

| | F-2B | F-0.8B |
|---|---|---|
| T3: backup used | 17.5% (all web) | 18.9% (all web) |
| T2: backup used | 12.7% (28 web, 6 other FDA label) | 11.6% |
| T6: backup used | 24.1% | 24.1% |

- Every backup answer carried its source link. There were 0 backup errors across all runs.
- **App bug, frozen and reported, not fixed:** web answers still end with the standard footer "This is information from the FDA label, not medical advice for you", which mislabels the source. The "From the web (site), not your label, may be wrong" badge appears above it.

### Speed and memory (M5 Pro, 24 GB, MLX)

| | Median | p90 |
|---|---|---|
| Label path, C-2B phone tier (T3) | 0.22 s | 0.64 s |
| Label path, C-0.8B (T3) | 0.31 s | 1.18 s |
| Full app F-2B with web (T3) | 2.7 s | 4.9 s |
| Passages only (D) | 9–14 ms | — |

| Model server | Peak memory |
|---|---|
| 2B fine-tune | 5.29 GB |
| 2B base | 4.81 GB |
| 0.8B fine-tune | 2.82 GB |
| 0.8B base | 2.38 GB |
| T1 batch runs (2B, larger prompts) | 6.3–6.8 GB |

**Phones and browsers** (from [Gate 1](gate1.md), not re-measured):
- **iPhone 17e Safari, 0.8B fine-tune.** About 16 tok/s decode and 195 tok/s prefill, so the first token arrives 4.9 s into a 963-token prompt.
- **iPhone 17e Safari, 2B fine-tune.** It crashes the tab and does not fit.
- **M5 Pro Chrome (WebGPU).** The 2B fine-tune decodes at 58–60 tok/s and the 0.8B at 80–84 tok/s. WebKit runs the 2B at 36 tok/s.

## Every result where PillProof loses

1. **T3, C vs B, both graders.** The fine-tune does worse than the base model given the same passages: −11.9 [−20.1, −2.9] acceptable on phone and −14.0 on desktop by the AI grader, and −9.1 correct on phone by the Gate 2 grader. It over-declines consumer phrasing.
2. **T2, C vs B.** −9.3 [−13.8, −5.0] correct (phone).
3. **T1, 0.8B wrong rate.** C-0.8B gives more wrong answers than B-0.8B: +5.1 [+2.8, +7.4] with phone passages and +8.1 [+6.2, +10.1] with oracle passages. B-0.8B gets its low wrong rate by declining 79% (phone) and 91% (oracle) of answerable questions.
4. **T1 sample, AI grader.** C-2B is below B-2B, −4.8 [−8.3, −1.4], although the Gate 2 grader has C 27 points ahead on the same items. Counting correct declines, they tie (83.6% each), so without correct citations, the fine-tune's T1 advantage disappears.
5. **E beats C and F on every set.**
   - T1 sample: 84.6 vs 71.6.
   - T3: 96.5 vs 55.2. Even under the strict rule, E 67.1 beats F 49.0.
   - T2: 83.5 vs 19.8.
   - T6: 96.6 vs 31.0, and E had no web.
6. **The passage-only fallback D beats C and F on T3** (69.9 vs 53.8 / 55.2, AI grader), and it is fastest.
7. **The web adds little outside T6.** +1.4 on T3 and +0.4 on T2, against +10.3 on T6.
8. **C's and F's wrong rate on T3 is higher than B's** by the AI grader (10.5–11.9% vs 2.8–4.2%). By the Gate 2 grader it is lower (2.8% vs 21.7%). The graders disagree on whether the passages C falls back to count as an answer.
9. **T6.** A-2B (no label) gets more useful-correct answers than F (34.5 vs 31.0), at the cost of 8 dangerous answers. F has 1 dangerous answer (T6-19).
10. **T5.** The fine-tune fails as a change judge (100% false flags). The base model does not beat the similarity rule.
11. **T4 not done.** Voice was not evaluated.
12. **The 2B model does not run on the target phone** (Gate 1). Phones get the 0.8B, which is 3.2 points less correct on T1.
13. **Desktop passages make C worse on T1, not better.** The wrong rate is 16.5% on desktop against 12.6% on phone, so the laptop setting gives more wrong answers.

## Disclosures

- **No human or blind grading.** The plan's human-graded measures were replaced by automatic and AI grading at the team's request:
  - blind grading of T3;
  - the pharmacist harm sample;
  - a 100-item human check of the T1 grader.
- **The AI grader was calibrated on 139 Gate 2 dev replies, read by one unblinded human, not on final answers.** Its agreement with the Gate 2 grader on T1 is low (κ 0.27).
- **The AI grader may credit correct general knowledge** on label-silent questions. This helps E and A. The strict T3 table removes that credit.
- **Truncated replies.** At 1,024 max tokens, E was cut off on 5 T3, 1 T6, 42 T2 and 122 T1-sample replies. The truncated text was graded as is.
- **Empty E replies.** On 6 T1-sample items and 1 T2 item, E used the whole token limit before writing any visible text. These were not graded, which slightly favours E.
- **Unparseable grader replies.** 1 on T3, 4 on T2 and 3 on the T1 sample were left out. So E has 267 graded T2 rows and 493 T1-sample rows, and its paired n is 267 / 491–493.
- **A-2B harness bug.** The first A-2B launch crashed on a path bug in `gen_plain.py` before writing any output. The bug was fixed (`out = FINAL / a.out`) and A-2B was run once. No result was seen before the fix.
- **T2 drug names.** For 149 T2 labels without an openFDA generic name, the app medicine was built from MedicationQA's `focus_drug`, with form "Oral Tablet".
- **T3 gold matching** for the Gate 2 grader uses containment or Jaccard ≥ 0.7, because the app builds its own prompt (see [Grading](#grading)).
- **D is identical at both tiers.** The fallback shows the same top passages at phone and desktop.
- **Shared runs.** C-2B desktop / F-2B, and C-0.8B / F-0.8B, are each one run graded at two points. This is not selection between runs.
- **One step was not done:** T4.
- **Showcase.** [showcase.md](showcase.md) shows 10 hand-picked examples: 9 answers the AI grader rated acceptable, plus one label-change alert. They are selected examples, not typical output.

## Commands

All scripts are in `train/scripts/final/`. Outputs go to `~/waicy-work/data/build/final/`.

```sh
# T1: prompts, retrieval, generation + Gate 2 grading (phase 1: phone; phase 2: desktop and oracle)
~/waicy-work/envs/mlx/bin/python train/scripts/final/t1_prep.py embed|prompts|retrieval
PHASE=1 train/scripts/final/run_t1.sh ; PHASE=2 train/scripts/final/run_t1.sh
# app pipeline runs (B, C, D, F on T3/T2/T6), one MLX model server at a time
python3 train/scripts/final/t2_fetch.py && python3 train/scripts/final/app_items.py
train/scripts/final/run_app.sh            # uses mlx_server.py + app/eval/final_harness.ts
# A (base model, no label) and E (Claude)
python3 train/scripts/final/gen_plain.py sample
python3 train/scripts/final/gen_plain.py run --set t3 --out app/t3_A2b.jsonl
datapipe/.venv/bin/python train/scripts/final/claude.py      # E
# T5
~/waicy-work/envs/mlx/bin/python train/scripts/final/t5_run.py --name base-2b
~/waicy-work/envs/mlx/bin/python train/scripts/final/t5_run.py --name tuned-2b --adapter
~/waicy-work/envs/mlx/bin/python train/scripts/final/t5_run.py --score
# grading and summary
python3 train/scripts/final/t3_grade.py
datapipe/.venv/bin/python train/scripts/final/grade_ai.py calib
datapipe/.venv/bin/python train/scripts/final/grade_ai.py grade
python3 train/scripts/final/summarize.py   # -> final/summary.json
```
