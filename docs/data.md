# Data pipeline

Code is in `datapipe/` (uv project, Python 3.12). Run all commands from `datapipe/`:

```bash
uv sync
uv run python -m medlabel_data.fdarx.ingredients   # map FDARxBench labels -> active ingredient(s)
uv run python -m medlabel_data.fdarx.split         # T1 train/dev/test by ingredient
uv run python -m medlabel_data.fdarx.align         # answers -> label sentence numbers
uv run python -m medlabel_data.fdarx.build         # MLX-LM chat files (+ decline examples)
uv run python -m medlabel_data.fdarx.audit         # 100-item hand-audit sheet
uv run python -m medlabel_data.medqa               # T2 (MedicationQA)
uv run python -m medlabel_data.labelfetch          # T3/T5 label versions (needs confirmed drug list)
uv run pytest -q                                   # splitter/section/alignment tests
```

**Data location.** Raw downloads and build outputs are not in git. The data root is `$WAICY_DATA` if set, otherwise `~/waicy-work/data` if it exists, otherwise `<repo>/data/` (gitignored). The agent was not allowed to write to `~/waicy-work/data`, so everything is currently in `<repo>/data/` (about 810 MB). To move it, run `mv data ~/waicy-work/data`; the code picks up the new location automatically.

The output format for the model is in [output-format.md](output-format.md).

## Shared tools

- `labels.py`: clients for the openFDA drug label API and DailyMed web services (SPL list, version history, SPL XML), with an on-disk cache.
- `spl.py`: SPL XML → sections. Each section keeps its LOINC code, title, category, text, and parent. Lists and tables become text; highlights are skipped.
- `sections.py`: LOINC section codes → categories (indications, dosage, warnings, …), plus fallback rules based on titles and PLR numbers. It also tags which categories are patient-relevant.
- `sentences.py`: a deterministic sentence splitter. It handles abbreviations ("e.g.", "mg.", "U.S."), decimals, list bullets and "°C." It will be ported to JavaScript for the browser, so it uses no ML. Golden cases are in `tests/fixtures/sentence_cases.json`. Known limitation: "U.S. Distributed by" is not split.

## T1 and training data: FDARxBench (Apache-2.0)

- **Split.** 699 labels map to 345 active ingredients. Labels that share an ingredient, including combination products, are grouped by connected components, so no ingredient appears in more than one split. Manual ingredient fixes are in `config/fdarx_ingredient_overrides.json`. Seed 2026.

  | split | labels | ingredients | QA items |
  |---|---|---|---|
  | train | 499 | 244 | 12,042 |
  | dev | 63 | 43 | 1,747 |
  | test (T1) | 137 | 58 | 3,418 |

  One large hormonal-contraceptive component, about 970 items, landed in test.

- **Alignment.** Each reference answer is matched to the sentences of its gold passage, falling back to the cited sections, by greedy token coverage: add the sentence that covers the most new answer tokens (at least 2) and stop at 12 sentences. An item is kept if coverage is at least **0.8 (factual)** or **0.9 (multihop)** and there is no hard fail.
  - Hard fails: a number in the answer that is missing from the cited sentences (984), no sentence selected (164), more than 12 sentences needed (78), and no gold passage (64).
  - Kept: **8,675 of 13,273** items.
  - Kept counts if one threshold were used for all tasks: 0.5 → 11,645, 0.6 → 11,160, 0.7 → 10,343, 0.8 → 9,257, 0.9 → 7,807, 1.0 → 6,917.
  - Details are in `data/build/fdarx/align_report.json`.
- **Prompts.** A prompt has the gold passage(s) plus distractor passages from the same label, up to 5 passages and about 5,000 characters. Long passages are trimmed to a window around the answer sentences.
- **Declines.** For a kept item, every passage that covers the answer (coverage ≥ 0.4) is removed and replaced with other passages from the same label. The example is kept only if the remaining prompt covers less than 0.5 of the answer. Declines are 30% of train and dev. Test gets declines equal to half its answerable count, plus FDARxBench's own 882 refusal items.
- **Patient relevance.** Each item is tagged *core* (all answer sections patient-relevant), *mixed*, or *technical*. Train keeps core items with probability 1.0, mixed 0.7, and technical 0.4. 7,146 of the 8,675 kept items are core, far more than the plan's estimate of about 2,000.
- **Output** in `data/build/fdarx/mlx/` (seed 7):

  | file | examples | answerable | decline | FDARxBench refusal |
  |---|---|---|---|---|
  | train.jsonl | 7,826 | 5,478 | 2,348 | — |
  | valid.jsonl | 1,317 | 922 | 395 | — |
  | test.jsonl (T1) | 3,378 | 1,664 | 832 | 882 |

- **Hand audit (for the project owner).** `data/build/fdarx/audit/audit_100.md` (readable) and `audit_100.csv` (fill in `verdict` and `notes`). The sheet has 100 random train items: 64 answerable and 36 decline. Check that the cited sentences really answer the question and that each decline is truly unanswerable from the prompt.

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
