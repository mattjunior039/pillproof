# Label changes (plan section 5, T5, Gate 3)

This page covers how changes between label versions are found, how many there are, the Gate 3 check, the T5 marking sheet, the model-judging harness and the app data file.
Code is in `datapipe/src/medlabel_data/changes/`. Large outputs go in `~/waicy-work/data/build/changes/` and are not in git.

```bash
cd datapipe
uv run python -m medlabel_data.changes.build      # all version pairs -> candidates.jsonl, pairs.jsonl, drugs.json
uv run python -m medlabel_data.changes.sample dev # 80-item development sample (eval/changes_dev_marks.csv)
uv run python -m medlabel_data.changes.sample t5  # T5 sheet (150) + pharmacist subset (30); never overwrites
uv run python -m medlabel_data.changes.appdata    # app/data/label_changes.json
# after T5 is fully marked, and only when the GPU is free:
PYTHONPATH=src ~/waicy-work/envs/mlx/bin/python -m medlabel_data.changes.judge \
    --model ~/waicy-work/models/Qwen3.5-2B --name base-2b
PYTHONPATH=src ~/waicy-work/envs/mlx/bin/python -m medlabel_data.changes.judge \
    --model ~/waicy-work/models/Qwen3.5-2B --adapter-path ~/waicy-work/models/adapters/<adapter> --name tuned-2b
```

## Method

**Versions.** Every archived DailyMed version of the 25 confirmed labels ([data.md](data.md)) is used. Versions are ordered by DailyMed published date, then version number. Effective dates can go backwards, so they are not used for ordering. A version number listed twice in a history (pantoprazole and donepezil) is kept once, at its earliest date. Each consecutive pair is compared: 400 versions give 375 pairs.

**Safety sections only** (plan section 3, item 15), chosen by LOINC section code (`sections.py`) and grouped so the old and new FDA label formats line up:

| Group | LOINC codes |
|---|---|
| Boxed warning | 34066-1 |
| Contraindications | 34070-3 |
| Warnings and precautions | 43685-7, 34071-1, 42232-9, 34072-9, 34075-2 (old-format PRECAUTIONS keeps only General, Laboratory tests, Drug interactions and Information for patients) |
| Drug interactions | 34073-7, 34074-5 |
| Patient information | 34076-0, 68498-5, 88436-1, 42231-1, 42230-3 (Instructions for use 59845-8 is dropped) |

Subsections without their own safety code (old-format Pregnancy, Pediatric use, Carcinogenesis) are dropped by code, or by title when the code is the generic 42229-5.

**Sentences.** Section text is re-flowed first: lines broken in the middle of a sentence are rejoined, and missing spaces after full stops are restored. Then the project sentence splitter is applied. Revision lines, manufacturer and address lines, phone and web lines, document codes, bare headings and leftover cross-reference fragments ("Warnings and Precautions (5.1)]") are not compared.

**Comparison key** (`normalize.py`). Sentences are compared on a normalized key, not raw text. The key strips:
- markup and table separators;
- bullets and list numbering, including inside table cells;
- cross-references such as "(5.2)" or "[see Warnings and Precautions (5.1)]";
- quote, dash and space variants;
- fraction and degree symbols;
- case.

**Alignment** (`align.py`, details in its docstring). Inside each group of each version pair:
1. Equal keys are matched, whatever their position. Renumbering and moving a sentence within a group are not changes.
2. A sentence moved to another group is matched.
3. A sentence split into a bullet list, or two sentences joined, is matched: exactly, or nearly (similarity ≥ 0.9).
4. Leftover old and new sentences are paired with the closest sentence (token similarity ≥ 0.5). These are **altered**.
5. Other leftover sentences are **added** or **removed**, each with its closest sentence in the other version as context. A sentence that only repeats one already on the other side is counted, not listed.
6. A word substitution made the same way in at least 3 sentences of the same update (for example "tramadol hydrochloride" → "tramadol hydrochloride tablets") is a label-wide edit and is dropped. This happened 295 times. Edits that touch a number, a negation, a modal or a quantity word are never dropped this way.
7. A whole new or removed subsection becomes one **section added/removed** event, for example a new Medication Guide or a new warning subsection.

**Format conversions.** Some labels moved from the old FDA format to the newer format (the 2006 "PLR" rule). Those updates rewrite and reorganize everything:
- amlodipine v1→v4
- metformin v17→v18
- levothyroxine v1494→v1506
- omeprazole v1→v4
- pantoprazole v4→v5
- donepezil v1→v2, v2→v3, v3→v4 (DailyMed history alternates between a generic-format and a PLR document)

Their candidates are kept in `candidates.jsonl` with `format_conversion: true`. They are left out of the dev sample, T5 and the app's sentence list. The app shows each one as a single "label rewritten in the newer FDA format" event. History depth still counts from the earliest version.

**Noise.** The first naive run (raw sentence text, no re-flow, no filters) gave about 6,800 candidates. Most came from line breaks, product-name edits, whole new leaflets and reformatting. The current build gives 3,444 candidates in total. Outside format conversions it gives 2,908 sentence-level candidates (876 altered, 1,287 added, 745 removed) and 30 section events. Of 75,220 new-version safety sentences, 71,475 matched an old sentence exactly after normalization, 117 matched as split/merge and 9 as moves.

## Counts per drug and history depth

Counts exclude format-conversion updates. "History from" is the earliest version compared, which is how far back the change history goes. "Pairs changed" counts consecutive versions with at least one safety candidate.

| Drug | Versions | History from | Latest | Pairs changed | Altered | Added | Removed | Section events | Baseline: meaning changed | Format conversions |
|---|---|---|---|---|---|---|---|---|---|---|
| atorvastatin | 7 | 2024-01-05 (v1, PLR) | 2026-07-15 | 1/6 | 2 | 2 | 2 | 0 | 5 | – |
| simvastatin | 8 | 2021-06-01 (v1, PLR) | 2025-04-03 | 4/7 | 36 | 66 | 77 | 5 | 165 | – |
| lisinopril | 2 | 2024-04-26 (v1, PLR) | 2025-05-05 | 0/1 | 0 | 0 | 0 | 0 | 0 | – |
| losartan | 7 | 2021-06-01 (v1, PLR) | 2026-01-21 | 1/6 | 0 | 1 | 0 | 0 | 1 | – |
| amlodipine | 25 | 2006-11-17 (v1, old) | 2025-06-09 | 9/24 | 6 | 21 | 24 | 0 | 45 | v1→v4 |
| metoprolol | 4 | 2023-07-03 (v2, PLR) | 2026-03-06 | 0/3 | 0 | 0 | 0 | 0 | 0 | – |
| carvedilol | 3 | 2023-11-28 (v1, PLR) | 2026-08-03 | 0/2 | 0 | 0 | 0 | 0 | 0 | – |
| hydrochlorothiazide | 12 | 2007-09-14 (v1, old) | 2024-06-27 | 3/11 | 5 | 8 | 0 | 0 | 10 | – |
| furosemide | 7 | 2016-04-20 (v1, old) | 2025-10-02 | 2/6 | 6 | 0 | 0 | 0 | 0 | – |
| metformin | 13 | 2011-03-10 (v3, old) | 2026-11-04 | 5/12 | 28 | 59 | 55 | 2 | 129 | v17→v18 |
| empagliflozin | 31 | 2014-08-15 (v1, PLR) | 2026-11-13 | 18/30 | 140 | 194 | 110 | 4 | 330 | – |
| levothyroxine | 24 | 2007-04-13 (v1, old) | 2024-02-29 | 8/23 | 20 | 17 | 7 | 0 | 25 | v1494→v1506 |
| omeprazole | 31 | 2008-02-22 (v1, old) | 2023-05-01 | 24/30 | 138 | 254 | 107 | 10 | 391 | v1→v4 |
| pantoprazole | 38 | 2007-06-14 (v1, old) | 2024-07-19 | 23/37 | 126 | 219 | 140 | 1 | 387 | v4→v5 |
| apixaban | 29 | 2013-01-15 (v1, PLR) | 2026-11-12 | 14/28 | 80 | 106 | 40 | 1 | 169 | – |
| rivaroxaban | 60 | 2011-07-12 (v1, PLR) | 2026-09-11 | 27/59 | 155 | 215 | 104 | 3 | 334 | – |
| warfarin | 17 | 2015-03-16 (v1, PLR) | 2025-06-23 | 8/16 | 22 | 44 | 32 | 0 | 81 | – |
| clopidogrel | 5 | 2020-07-01 (v1, PLR) | 2025-06-11 | 2/4 | 3 | 10 | 0 | 0 | 10 | – |
| gabapentin | 9 | 2024-07-24 (v1, PLR) | 2026-08-06 | 2/8 | 2 | 9 | 0 | 1 | 8 | – |
| sertraline | 7 | 2023-09-26 (v1, PLR) | 2025-07-24 | 1/6 | 2 | 0 | 0 | 0 | 1 | – |
| donepezil | 27 | 2007-05-31 (v1, old) | 2026-06-30 | 9/26 | 23 | 7 | 8 | 2 | 24 | v1→v2, v2→v3, v3→v4 |
| tamsulosin | 16 | 2013-05-03 (v1, PLR) | 2023-11-20 | 7/15 | 12 | 8 | 8 | 0 | 16 | – |
| montelukast | 5 | 2021-06-01 (v1, PLR) | 2025-06-25 | 0/4 | 0 | 0 | 0 | 0 | 0 | – |
| alendronate | 8 | 2021-06-01 (v1, PLR) | 2026-03-16 | 1/7 | 7 | 10 | 4 | 0 | 17 | – |
| tramadol | 5 | 2022-10-04 (v36, PLR) | 2026-01-28 | 4/4 | 63 | 37 | 27 | 1 | 76 | – |
| **Total** | **400** | | | | **876** | **1,287** | **745** | **30** | **2,224** | |

Lisinopril, metoprolol, carvedilol and montelukast have no safety-section change in their archived history. Losartan and sertraline have one each. Furosemide's 6 altered pairs all scored as rewording. Most changes come from long histories (rivaroxaban 60 versions, pantoprazole 38) and from patient leaflets rewritten in place.

## Baseline: text-similarity rule

`baseline.py` labels a candidate "meaning changed" when its similarity is below θ, and "reworded" otherwise. Similarity is computed on the comparison key against the paired sentence, or against the closest sentence for added and removed ones.

θ = 0.75 was chosen on the development sample only, never on T5:

| θ | Catch rate | False-flag rate | Accuracy |
|---|---|---|---|
| 0.5 | 0.74 | 0.32 | 0.71 |
| 0.6 | 0.81 | 0.35 | 0.74 |
| **0.75** | **0.91** | **0.51** | 0.71 |
| 0.85 | 0.93 | 0.65 | 0.66 |

0.6 has the best accuracy. 0.75 was chosen because a missed safety change matters more than an extra flag. The rule is weak at telling rewording from real change: it flags half of the rewordings. That is the gap the model is meant to close.

## Development sample and Gate 3

Gate 3: fewer than about 1 in 5 flagged changes are only reformatting.

- **Flagged changes** means every sentence-level candidate the pipeline outputs outside format conversions (2,908).
- **Dev sample.** I drew a simple random sample of 80 (seed 20261121), stored in `datapipe/eval/changes_dev_marks.csv`. I marked it myself for development only, as "meaning changed", "reworded" or "formatting only". It is kept apart from T5: T5 excludes these IDs, and θ was never tuned on T5.
- **Result:** 43 meaning changed, 26 reworded, 11 formatting only.

| Estimate | Formatting only | 95% interval (Wilson) |
|---|---|---|
| All flagged candidates | 11/80 = **13.8%** | 7.9% to 23.0% |
| Candidates the baseline calls "meaning changed" | 6/58 = 10.3% | 4.8% to 20.8% |

**Gate 3 status: passes on the point estimate (13.8% < 20%), but not conclusively.** The upper end of the interval is above 20%.

The 11 formatting-only items were:
- a bullet list merged into one sentence;
- headings and table headers that survived the filters;
- a cross-reference typed without a space;
- an old line cut at a hard line break;
- pointers such as "See FDA-approved patient labeling";
- a heading glued to its sentence.

The 26 rewordings are mostly edits like "should be discontinued" → "Discontinue", "proton pump inhibitor" → "PPI", "leaflet" → "Medication Guide" and "patients" → "people". These are the cases the model should learn to call "reworded".

T5's `only_formatting` column will give a second, independent estimate from the user's marks.

## T5 marking sheet (the user marks; no model has seen it)

- `~/waicy-work/data/build/changes/t5/t5_sheet.csv`: fill in `mark` ("meaning changed" or "reworded"), plus `only_formatting` (y/blank) and `notes`.
- `~/waicy-work/data/build/changes/t5/t5_sheet.md`: the same 150 items, easier to read.
- `~/waicy-work/data/build/changes/t5/t5_key_hidden.jsonl`: links each T5 id to its candidate, stratum and sampling weight. Do not open it while marking.

How the sample was drawn (`sample.py`, seed 5):
- 150 items from the 2,908 non-conversion sentence candidates, excluding the dev sample.
- Round-robin over drugs, then over four change types:
  - altered with similarity ≥ 0.85 (43 items);
  - altered with lower similarity (34);
  - added (45);
  - removed (28).
- At most 3 items from any one version pair, in shuffled order.
- All 21 drugs that have candidates are included: 8 each for most drugs; atorvastatin 6, furosemide 6, warfarin 7, sertraline 2, losartan 1.
- The sheet shows no similarity score or baseline label.

**Pharmacist subset:** `pharmacist_sheet.csv` / `.md` (30 items, a subset of T5, spread over the 21 drugs, seed 30). It has the same columns plus `plain_language_line` and `plain_language_accurate`. The plain-language lines are filled in from the chosen model's checked explanations after T5 is scored. The pharmacist then marks both the change and whether the line is accurate. Agreement with the user's marks is reported.

## Model-judging harness (`judge.py`), not yet run

For each item the model gets:
- for an altered pair: the old and new sentence;
- for an added or removed sentence: that sentence plus the closest one in the other version.

It must answer `LABEL: meaning changed|reworded` and `EXPLANATION: The label …` (one plain sentence). Settings: greedy decoding, thinking off, and any `<think>` block is stripped.

Checks on the explanation:
- The app's number check (`text.restatement_problems`): every number, unit and drug name must appear in the old, new or closest sentence.
- An advice check: no "you should", "stop taking", "talk to your", and similar.

An explanation that fails either check is dropped and the label is kept. An unparsable answer counts as "meaning changed", which is what the app would show. Every output carries "Ask your pharmacist or doctor before changing anything."

**Guard:** on T5 the harness exits unless all 150 rows have a valid mark. `--dry-run` prints prompts without loading a model. `--backend mock` is used in tests. `--split dev` runs on the dev sample.

Each run scores the model and the baseline on the same items. It reports:
- confusion matrix, catch rate, false-flag rate and accuracy;
- 95% intervals by resampling drugs (items from one drug are not independent);
- the same rates by change type;
- a weighted estimate for all candidates, using the T5 stratum weights;
- the number of dropped explanations and why.

Outputs go to `~/waicy-work/data/build/changes/judge/`. Methods to run, as in the plan:
1. the baseline, scored by every run;
2. the untuned Qwen3.5 (`--model` only);
3. the fine-tuned model (`--adapter-path` or a fused model, from the parallel training session).

## App data file

`app/data/label_changes.json` (248 KB, about 50 KB gzipped) is built by `appdata.py`. Per drug it has:
- brand, set id, manufacturer and number of versions;
- `history_from` (the earliest version compared and its date) and the latest version;
- dated updates, newest first.

Each update has:
- the DailyMed published and effective dates and the from/to version;
- counts per section;
- its changes: section group and subsection, kind, old and new text copied from the labels by code, `plain_language: null` (a placeholder until a checked model line exists), `judged_by`, and the note "Ask your pharmacist or doctor before changing anything."

What is listed:
- changes the current judge calls "meaning changed" (today the baseline), plus section events;
- format conversions, as one `format_rewrite` event each;
- sentence pairs only for the 3 most recent updates per drug, at most 25 per update, ordered boxed warning → contraindications → warnings → interactions → patient information;
- older updates with their counts only;
- trademark notices ("Rotachrom® is a registered trademark of …") are left out.

The full list is in `~/waicy-work/data/build/changes/label_changes_full.json`. Nothing in the file is phrased as a reason to stop a medicine. When the fine-tuned model is chosen, rerun `appdata` with its labels and checked lines. If Gate 3 or the model fails, the plan's fallback applies unchanged: the app shows dates and old and new text without explanations.

## Known limitations

- Remaining noise that the dev sample shows:
  - old-format lines broken before a capitalized word;
  - words broken by a space ("tak ing");
  - typo fixes;
  - grammar-only edits ("is" → "are").
- An added sentence is judged against only its single closest old sentence. Information that moved and was split across several sentences can look added.
- Product-description lines inside patient leaflets (inactive ingredients, dyes) are kept, because ingredient changes can matter to allergic patients.
