# Data pipeline

Code is in `datapipe/` (uv project, Python 3.12). Run all commands from `datapipe/`:

```bash
uv sync
uv run python -m medlabel_data.fdarx.ingredients   # map FDARxBench labels -> active ingredient(s)
uv run python -m medlabel_data.fdarx.split         # T1 train/dev/test by ingredient
uv run python -m medlabel_data.fdarx.align         # answers -> label sentence numbers
uv run python -m medlabel_data.fdarx.build         # MLX-LM chat files (+ decline examples)
uv run python -m medlabel_data.fdarx.audit         # 100-item hand-audit sheet
uv run python -m medlabel_data.fdarx.decline_audit # 50-item decline spot-check sheet (train/valid)
uv run python -m medlabel_data.medqa               # T2 (MedicationQA)
uv run python -m medlabel_data.labelfetch          # T3/T5 label versions (needs confirmed drug list)
uv run pytest -q                                   # splitter/section/alignment tests
```

**Data location.** Raw downloads and build outputs are not in git. The data root is `$WAICY_DATA` if set, otherwise `~/waicy-work/data` if it exists, otherwise `<repo>/data/` (gitignored). The data currently lives in `~/waicy-work/data`. Paths below starting `data/` are relative to the data root.

The output format for the model is in [output-format.md](output-format.md).

## Shared tools

- `labels.py`: clients for the openFDA drug label API and DailyMed web services (SPL list, version history, SPL XML), with an on-disk cache.
- `spl.py`: SPL XML → sections. Each section keeps its LOINC code, title, category, text, and parent. Lists and tables become text; highlights are skipped.
- `sections.py`: LOINC section codes → categories (indications, dosage, warnings, …), plus fallback rules based on titles and PLR numbers. It also tags which categories are patient-relevant.
- `sentences.py`: a deterministic sentence splitter. It handles abbreviations ("e.g.", "mg.", "U.S."), decimals, list bullets and "°C." It will be ported to JavaScript for the browser, so it uses no ML. Golden cases are in `tests/fixtures/sentence_cases.json`. Known limitation: "U.S. Distributed by" is not split.

## T1 and training data: FDARxBench (Apache-2.0)

- **Split.** 699 labels map to 345 active ingredients. Labels that share an ingredient, including combination products, are grouped by connected components, so no ingredient appears in more than one split. Manual ingredient fixes are in `config/fdarx_ingredient_overrides.json`. Seed 2026.

  | split | labels | ingredients | QA items | largest family |
  |---|---|---|---|---|
  | train | 543 | 231 | 12,041 | 9.6% |
  | dev | 64 | 40 | 1,699 | 9.9% |
  | test (T1) | 92 | 74 | 3,467 | 4.1% |

  A family (connected component) may go to dev or test only if it holds at most 10% of that split's target item count; larger families go to train. This moved the hormonal-contraceptive cluster (about 970 items, off-target for older adults) from test to train, and keeps four other large families (acetaminophen combinations, antihypertensive combinations, loratadine, diabetes combinations) in train.

- **Alignment.** Each reference answer is matched to the sentences of its gold passage, falling back to the cited sections, by greedy token coverage: add the sentence that covers the most new answer tokens (at least 2) and stop at 12 sentences. An item is kept if coverage is at least **0.8 (factual)** or **0.9 (multihop)** and there is no hard fail.
  - Hard fails: a number in the answer that is missing from the cited sentences (984), no sentence selected (164), more than 12 sentences needed (78), and no gold passage (64).
  - Kept: **8,675 of 13,273** items.
  - Kept counts if one threshold were used for all tasks: 0.5 → 11,645, 0.6 → 11,160, 0.7 → 10,343, 0.8 → 9,257, 0.9 → 7,807, 1.0 → 6,917.
  - Details are in `data/build/fdarx/align_report.json`.
- **Prompts.** A prompt has the gold passage(s) plus distractor passages from the same label, up to 5 passages and about 5,000 characters. Long passages are trimmed to a window around the answer sentences.
- **Declines.** For a kept item, every passage that covers the answer is removed: passages that hold a gold sentence, share the gold section heading, or whose words cover ≥ 0.4 of the answer. Other passages from the same label replace them. Then two checks run:
  1. **Support check on the rest of the label** (added 2026-11-16, `fdarx/support.py`). The reference answer is checked against **every remaining sentence of the full label**, not only the passages shown. The item is dropped if the answer is supported there. The check is deliberately loose: it is better to lose a good decline item than to train the model to decline an answerable question.
     - Words are canonicalised with a small clinical ↔ lay synonym map (21 groups, e.g. geriatric/older → elderly, renal → kidney, hepatic → liver, pediatric → child).
     - Greedy alignment: each sentence must add at least **1** new answer word, up to **4** sentences. Headings of the chosen passages count.
     - "Supported" means coverage **≥ 0.5** *and* every number, unit and drug name in the reference answer appears in the chosen sentences, anywhere else in the remaining label, or in the drug name.
  2. **Shown-passage check.** The example is kept only if a greedy alignment over the shown passages covers < 0.5 of the answer.

  Dropped items are replaced from the remaining answerable items of the same split, using their own seeded order. No item was converted into an answerable example, for two reasons:
  - Every decline's question already appears in the same split as an answerable example, so a converted copy would only duplicate it.
  - A negative control showed that lexical "strong" alignment cannot be trusted for this. Another dev label's answer, with the drug name swapped, against the full label: under a strict rule (standard aligner, coverage ≥ 0.8/0.9, all numbers and key facts present, ≤ 4 sentences) the wrong answers were flagged as "supported" 36 times out of 378, against 12 for the real items.

  Under the loose check, the same negative control (full label, 3 seeds) flags 111–144 of 378 wrong answers (29–38%) as supported, against 242 of 378 (64%) old dev declines. So the check over-drops and is only weakly discriminative. It removes many truly answerable declines, but it does not prove that an answer is absent from what remains. The 50-item spot-check below estimates how many answerable declines are left.

  | split | old declines | removed (supported elsewhere) | converted | kept | refilled | new declines | decline share |
  |---|---|---|---|---|---|---|---|
  | train | 2,273 | 1,447 (64%) | 0 | 824 | 1,106 | 1,930 | 26.7% (target 30%) |
  | valid (dev) | 378 | 242 (64%) | 0 | 136 | 175 | 311 | 26.1% (target 30%) |
  | test (T1) | 949 | 579 (61%) | 0 | 370 | 370 | 740 | 28.0% of non-refusal items (target 33%) |

  - "Kept" counts old items still chosen. In train, 2 surviving items failed the shown-passage check after their distractors changed.
  - The pool ran out before the target share: across all candidates, 3,360 train, 569 dev and 1,156 test items were "supported elsewhere".
  - The fix is code only and identical for every split. For T1, only these counts were computed; no model was run on it.
  - FDARxBench's own 549 refusal items are unchanged.
  - Answerable examples are byte-identical to the previous build. The old build is kept in `data/build/fdarx_pre_declinefix/`.
- **Patient relevance.** Each item is tagged *core* (all answer sections patient-relevant), *mixed*, or *technical*. Train keeps core items with probability 1.0, mixed 0.7, and technical 0.4. 7,146 of the 8,675 kept items are core, far more than the plan's estimate of about 2,000.
- **Output** in `data/build/fdarx/mlx/` (seed 7):

  | file | examples | answerable | decline | FDARxBench refusal |
  |---|---|---|---|---|
  | train.jsonl | 7,234 | 5,304 | 1,930 | — |
  | valid.jsonl | 1,193 | 882 | 311 | — |
  | test.jsonl (T1) | 3,188 | 1,899 | 740 | 549 |

  (Before the decline fix: 7,577 / 1,260 / 3,397, with 2,273 / 378 / 949 declines.)

- **Hand audit (for the project owner).** `data/build/fdarx/audit/audit_100.md` (readable) and `audit_100.csv` (fill in `verdict` and `notes`). The sheet has 100 random train items: 67 answerable and 33 decline. Check that the cited sentences really answer the question and that each decline is truly unanswerable from the prompt. Targets come from `mlx_plain/` when it exists. For the 65 answerable items whose ANSWER line was rewritten, the original line is shown beside it, so the audit also checks the rewrite. This sheet was drawn before the decline fix and has not been regenerated, so any verdicts already filled in are kept. Re-running `audit` would draw a different sample.
- **Decline spot-check (for the project owner).** `data/build/fdarx/audit/decline_check_50.md` and `decline_check_50.csv` contain 50 random decline items that survived the support check (40 train, 10 valid; never test).
  - Each item shows the question, the answer that was removed, the removed section headings, and the closest remaining sentences the check found.
  - `decline_check_labels/NN_<qid>.txt` is the full label text with the removed passages marked, so it can be searched with Ctrl-F.
  - Verdicts: `not_in_label`, `answerable_elsewhere` (fill in `where_found`), `partly`, or `bad_question`.

### Plain-language ANSWER lines (train and valid only; disclosed AI assistance)

FDARxBench reference answers are written in clinical language. The ANSWER lines in **train and valid only** were rewritten into plain language by a large language model. **T1 (test), T2 and T3 are never rewritten.** `mlx_plain/test.jsonl` is a byte-for-byte copy of `mlx/test.jsonl`.

- **Model and date.** Anthropic Claude Sonnet 5.5 (`claude-sonnet-5-5`) via the API, 2026-11. Prompt version v2. The exact system prompt is `SYSTEM` in `datapipe/src/medlabel_data/fdarx/rewrite.py`.
- **Model input.** The drug, the question, the cited label sentences and the original ANSWER line.
- **Instructions to the model:**
  - Restate only the original's facts.
  - Add no advice, warnings or background.
  - Keep every number exactly as written, plus its unit and every drug name.
  - Use short sentences and common words, aiming for a 6th–8th grade reading level.
  - Keep medical terms in parentheses after the everyday words.
  - Write a single line.
- **Automatic checks on every rewrite.** A rewrite that fails is retried once with the problems listed. If it fails again, the original line is kept.
  1. **The app's check** (plan §3): every number, unit and drug name must appear in the cited sentences (or the drug name line).
  2. **Preservation:** every number, unit and drug name in the original line must still be present.
  3. **No added advice:** words like doctor, pharmacist, call, seek, emergency or consult must not appear unless they are in the original or the cited sentences.
  4. **Shape:** one line, and not much longer than the original.
- **The SENTENCES line is never changed.** The prompt (system and user messages) is identical to `mlx/`, and the decline targets are unchanged.
- **Results (6,186 answerable train and valid rows):**

  | outcome | rows |
  |---|---|
  | passed on first try | 5,922 |
  | passed on retry | 171 |
  | both tries failed → original kept | 39 |
  | original itself fails the app check → not sent, kept | 54 |
  | **pass rate** | **98.5%** (6,093 / 6,186) |

  The 54 originals that fail the app check usually name a drug class or another drug that appears only in the reference answer (for example "nitroimidazole" or "penicillin"). Those lines teach restatements that the app would block, so they could also be dropped. They were kept to leave the training set unchanged otherwise.
- **Most common first-try failures:**
  - added advice (94);
  - a number not in the label (54), often copied from the question;
  - a missing unit (33);
  - a unit not in the label (29);
  - a missing number (17).
- **Reading level (median Flesch–Kincaid grade).**
  - Original lines: 14.6. Rewrites: 10.4, or 9.1 with the medical terms in parentheses removed.
  - The 6–8 target is not fully met. Drug names and required medical terms raise the score, and they cannot be removed without failing the checks.
  - The median rewrite is 1.24× the original's length.
- **Cost.** $12.48 for the full run (3.72 M input and 0.51 M output tokens at $2/$10 per million tokens). Two 50-item pilots (prompts v1 and v2) cost $0.24, so the total is about $12.75.
  - The v1 pilot passed 94% with a median grade of 9.7.
  - v2 stopped the model from adding facts and lengthening answers, and passed 100% of the pilot.
- **Output.** `data/build/fdarx/mlx_plain/{train,valid,test}.jsonl` uses the same format as `mlx/`. After the decline fix it was rebuilt with `rewrite --write` from the cached results; no new API calls were made. Train has 5,221 rewritten and 83 kept-original lines; valid has 872 and 10. `*_meta.jsonl` adds `answer_original`, `answer_plain` and `rewrite_status` for comparison.
  - Per-row results: `data/build/fdarx/rewrite/all_results.jsonl`.
  - Summary: `all_report.json`.
  - Readable comparison: `all_side_by_side.md`.
  - API response cache: `cache.jsonl`. A re-run costs nothing unless the prompt changes.
- **Commands:**

  ```bash
  # The key is read from $ANTHROPIC_API_KEY or ~/waicy-work/.env (never committed)
  uv run python -m medlabel_data.fdarx.rewrite --sample 50   # pilot + full-run cost estimate
  uv run python -m medlabel_data.fdarx.rewrite --all         # all train/valid answerable rows
  uv run python -m medlabel_data.fdarx.rewrite --write       # build mlx_plain/
  uv run python -m medlabel_data.fdarx.audit                 # audit sheet now shows plain targets
  ```

- **Disclosure.** Write-ups should say that the training targets' restatement lines were simplified by Claude Sonnet 5.5 under automatic number, unit and drug checks, and that no evaluation data was rewritten.

## T2: MedicationQA (CC BY 4.0), test only

`data/build/medqa/t2_all.jsonl` (690 consumer questions) and `t2_dailymed.jsonl` (290 whose reference answer came from DailyMed; 287 have a set_id and 268 of those set_ids are still current in openFDA). Each record has the question, focus drug, question type, reference answer, source URL, set_id, and the reference answer's section category. Never used for training.

## T3/T5: label versions for 25 drugs common in older adults

The list was confirmed by the project owner on 2026-11-15 and is in `config/t3_drugs.json`.

- **Resolver.** For each drug it picks the brand-name label from the original packager (oral, Rx), using openFDA plus DailyMed. If the brand label is gone, it uses the generic label from the original packager.
- **Download.** It downloads every version in the DailyMed SPL history to `data/labels/<ingredient>/<set_id>/vNNNN.{xml.gz,json}` with a `manifest.json`. 0 errors. Many consecutive versions are relabels with identical text.

| ingredient | brand | label used | versions | effective |
|---|---|---|---|---|
| atorvastatin | Lipitor | brand | 7 | 2023–2024 |
| simvastatin | Zocor | brand | 8 | 2021–2025 |
| lisinopril | Zestril | brand | 2 | 2024–2025 |
| losartan | Cozaar | brand | 7 | 2021–2026 |
| amlodipine | Norvasc | brand | 25 | 2006–2022 |
| metoprolol | Toprol-XL | brand | 4 | 2022–2026 |
| carvedilol | Coreg | brand | 3 | 2023–2026 |
| hydrochlorothiazide | — | generic | 12 | 2007–2024 |
| furosemide | Lasix | brand | 7 | 2016–2025 |
| metformin | Glucophage | generic | 13 | 2011–2026 |
| empagliflozin | Jardiance | brand (DailyMed) | 31 | 2014–2026 |
| levothyroxine | Synthroid | brand | 24 | 2006–2024 |
| omeprazole | — | generic | 31 | 2008–2023 |
| pantoprazole | Protonix | brand | 40 | 2007–2024 |
| apixaban | Eliquis | brand | 29 | 2012–2026 |
| rivaroxaban | Xarelto | brand | 60 | 2011–2026 |
| warfarin | — | generic | 17 | 2015–2025 |
| clopidogrel | Plavix | brand | 5 | 2020–2025 |
| gabapentin | Neurontin | brand | 9 | 2024–2026 |
| sertraline | Zoloft | brand | 7 | 2023 |
| donepezil | Aricept | brand | 28 | 2007–2022 |
| tamsulosin | Flomax | generic | 16 | 2013–2023 |
| montelukast | Singulair | brand | 5 | 2021–2025 |
| alendronate | Fosamax | brand | 8 | 2021–2026 |
| tramadol | Ultram | generic | 5 | 2022–2026 |

- DailyMed history only includes versions it has archived. Some labels restarted their history, for example Zestril has only 2 versions.
- To pin a different label, set `set_id` for that drug in the config.
- T3 questions are **not** written here. The project owner writes and locks them before seeing any model output.

## Licenses

- FDARxBench: Apache-2.0.
- MedicationQA: CC BY 4.0 (cite Ben Abacha et al., MedInfo 2019).
- openFDA and DailyMed label text: public domain (U.S. government / FDA).
