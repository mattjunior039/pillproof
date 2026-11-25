# Annotation workbook

All human work is in **one shared file** that the markers, the pharmacist and the testers all use in Google Sheets: `data/build/annotation/annotation_master.xlsx`, with one CSV per tab in `csv/`. Nobody is assigned rows by name. Each person picks the tab for their role and types their first name in the `name` column of every row they mark. The marks are merged back into the original sheets afterwards. The code is in `datapipe/src/medlabel_data/annotation/`. The outputs are in `data/build/annotation/` and are not in git.

## Tabs

| tab | who | rows | source sheet (marks are merged back here) | fill in |
|---|---|---|---|---|
| Start here | everyone | – | – | read: pick the tab for your role; type your first name in every row you mark; humans only, no AI tools; what to do, 2 worked examples and the time for each tab |
| Progress | everyone | – | – | nothing; formulas count rows done / total per tab and rows marked per name |
| Markers – T5 label changes | markers | 150 | `changes/t5/t5_sheet.csv` | `name`, `mark` (meaning changed / reworded), `only_formatting` (y / n), `notes` |
| Markers – T3 questions | markers | 143 | `t3/t3_draft.csv` | `name`, `user_status` (keep / edit / drop), `user_notes` |
| Markers – T6 questions | markers | 30 | `t6/t6_draft.csv` | `name`, `user_status` (keep / edit / drop), `user_notes` |
| Markers – Training audit | markers | 23 | `fdarx/audit/audit_review_20.csv` | `name`, `user_verdict` (ok / wrong_sentences / wrong_answer / should_decline / should_answer / bad_question), `user_notes` |
| Markers – Decline check | markers | 20 | `fdarx/audit/decline_review_20.csv` | `name`, `user_verdict` (not_in_label / answerable_elsewhere / partly / bad_question), `user_where_found`, `user_notes` |
| Second check | markers | 56 (T5 30, T3 21, T6 5) | the same sheets, as a second mark (`*_2`) | `name`, `answer`, `only_formatting` (T5 only), `notes` |
| Pharmacist | pharmacist | 30 | `changes/t5/pharmacist_sheet.csv` | `name`, `mark`, `only_formatting`, `clinically_important` (y / n), `notes` |
| Testers – usability | session runner | 20 empty sessions | `usability.csv` (new) | one row per test session, see below |
| Reference – label text | markers | 9,094 lines | – | nothing; the full label text for the audit and decline rows, one line per row (filter on `item_id`) |

Layout of every tab:
- Row 1 is a one-line "What to do" (merged, bold). The header is on row 2 (row 3 on the testers tab, under the session script) and is frozen.
- Each row has a stable `item_id` (`T5-001`, `T3-001`, `T6-01`, `AUD-001`, `DEC-02`, `PH-T5-004`, `U-01`) and, as the last column, `task`. Merging needs both.
- The grey columns are the item; the coloured columns are filled in. Choice columns have dropdowns; `name` is free text.
- One colour per role: markers blue, pharmacist purple, testers orange, info grey.
- Long label text is kept out of the task tabs: the audit and decline rows point to the Reference tab.

Only things the reviewer needs are shown. T3 shows the question, topic, whether it is answerable, the reference answer, the gold sentences or the decline evidence, and a DailyMed link. T6 shows the question, category, reference note, `dangerous_if`, the sources and the label text. Author notes, label versions, sentence numbers and similar fields stay in the source sheets.

### Second check

To measure agreement, about 20% of T5 and 15% of T3 and T6 appear a second time on the Second check tab. They have the same `item_id`, no first mark visible, and the item text in one cell. The note says: *Do these only if you did NOT mark the same item on another tab.* Rows are grouped by task (T5, then T3, then T6) and shuffled within each block. The set is a seeded, drug-stratified systematic sample (seed 2026, `split.double_set`):
1. Items are grouped by drug, with drugs in sorted order, and shuffled within each drug with `random.Random(f"{seed}:{task}:{drug}")`.
2. k = share × N, rounded half up. The items at positions ⌊i·N/k⌋ of that order are taken, so they are spread over the drugs.

### Pharmacist

The Pharmacist tab holds a subset of T5: the 30 rows have the same `t5_id` as their T5 rows (`PH-T5-004` is `T5-004`). The instructions use expert wording. A pharmacist marks them independently, and they are compared with the T5 marks. `clinically_important` is a new column. The `plain_language_*` columns of `pharmacist_sheet.csv` are left out because they would show model output. Checking the plain-language rewrites is a separate, later step.

### Testers – usability

One row per test session, filled in by the person running it. Above the header is a short script: it's the app being tested, not you; think aloud; stop any time; use the demo medicines; how to give each task and when to help; the 10 SUS statements; and the last 3 questions.

Columns:
- `name` (the session runner), `tester` (first name or a code only), `age_band` (under 18 / 18-39 / 40-59 / 60-69 / 70-79 / 80+), `phone`, `date`. No other personal data.
- For each of the 5 tasks (pick or scan a medicine, ask a dose question, ask a food or drink question, read a label-change alert, use voice): `<task>_done` (yes / no / with help), `<task>_minutes`, `<task>_comment`.
- `sus_1` … `sus_10` (1–5): the System Usability Scale (Brooke 1996), with "system" replaced by "app". The statements are in the script and in a note on each header cell. `sus_score` is a formula: odd items score − 1, even items 5 − score, sum × 2.5, blank until all 10 are filled.
- `would_use` (1–5), `what_confused_you`, `anything_unsafe_or_wrong`.

## Kept blind

The rule shown first is: *humans only, no AI tools, and don't look up the app's answers*.

The workbook never shows:
- AI verdicts or notes (`ai_*`);
- `t5_key_hidden`;
- `r3_status`;
- the decline-check `check_coverage`;
- support-check coverage numbers inside the T3/T6 evidence notes;
- any score, prediction or model output.

`tasks.BLOCKED` is checked on every header that is written, and writing fails if a blocked column would be shown. The only exception is the testers' own `sus_score`. AI notes are joined back only after merging, from the original sheets.

The training-audit rows show what the model was trained on: the cited sentences, the `target`, the original line from the benchmark, and (on the Reference tab) all sentences shown. They are training data, not model outputs.

## Commands

Run from `datapipe/`:

```bash
uv run python -m medlabel_data.annotation.build                                  # the shared file + CSVs
uv run python -m medlabel_data.annotation.merge ~/Downloads/annotation_master.xlsx --dry-run
uv run python -m medlabel_data.annotation.merge ~/Downloads/annotation_master.xlsx
```

`build` options: `--seed` (Second check sample), `--due` (shown on Start here, default 2026-11-23), `--out`.

## Google Sheets

1. Upload `annotation_master.xlsx` to Drive and open it with Google Sheets (or File → Import → Upload). Share it with the markers, the pharmacist and the testers.
2. Dropdowns, frozen headers, colours, the header notes and the formulas carry over. The formulas use only classic functions (COUNTA, COUNTIF(S), INDEX, MATCH, IFERROR, ROWS, SUM), so nothing is Excel-only. The Progress tab's name list uses two hidden helper columns (X and Y) that collect every name typed.
3. When everyone is done, download it with File → Download → Microsoft Excel (.xlsx) and run `merge` on it, starting with `--dry-run`.

Rebuilding the master replaces it with empty marks, so don't rebuild once people have started; download the shared copy instead.

## How marks are merged back

`merge` reads the shared file downloaded back as `.xlsx`, its tab CSVs, or per-person files from `split`. It accepts files or folders; folders are not searched recursively. It writes `merge_report.md`.

**Reading:**
- The header row is found in the first 10 rows of each tab: any table with `item_id` and `task` is read. Start here, Progress and the Reference tab are skipped.
- The task tabs are the first mark. The Second check tab (the table with an `answer` column) is the second mark: `answer` goes to the task's main mark, `notes` to its notes column, and `only_formatting` to `only_formatting`.
- The annotator is the `name` cell, with spaces trimmed. Rows with marks but no name are skipped with a warning, unless a default is given. `--default-annotator NAME` sets a default for every task; `--default-annotator pharmacist=NAME` sets it for one task only. Both can be repeated.
- `--alias TYPED=NAME` (repeatable, case-insensitive) maps a misspelt name to the right one, for example `--alias Jhon=John`.
- Choice values are matched ignoring case, spaces and underscores. Invalid values are reported and ignored.
- Warnings: rows left blank (counted per task), rows with notes but no main mark, unknown item ids, and incomplete usability rows (no tester code, or SUS partly filled).
- Different values for the same item and slot in two input files are an error.

**Writing:**
- First marks go into the source sheet as `annotator` plus the mark columns. Second marks go into `annotator_2` and `<mark>_2` (for example `mark_2`, `user_status_2`). The pharmacist's marks go into `pharmacist_sheet.csv`, which gets `annotator` and `clinically_important`.
- Tester sessions go into `data/build/annotation/usability.csv` (option `--usability`), one row per `U-NN`, with `sus_score` recomputed in Python.
- Existing marks are never overwritten. A filled cell may only receive the same value (names compared ignoring case). Every conflict is listed, and then the whole merge is aborted with nothing written. So merging the same file twice is safe, and changing a mark after a merge needs a deliberate edit of the source sheet.

**Agreement:**
- For each of T5, T3 and T6, Cohen's kappa and percent agreement are computed between the first mark and the Second check mark, on the main mark.
- Pairs where the same name gave both marks are left out of kappa, with a warning, and counted in their own column.
- With fewer than 20 pairs of different people the report says "too few" instead of giving a kappa.
- The pharmacist's `mark` is compared with the first T5 mark for the same `t5_id`.
- The report also gives the number of usability sessions and the mean SUS.

The T3 and T6 builders keep extra columns such as `annotator` and `*_2` when they rebuild their sheets (`t3.write_sheet`). The T5 sheet generator is on another branch and does not yet keep them. Rebuilding `t5_sheet.csv` after a merge would drop the merged marks, so merge only after T5 is final, or back the sheet up first.

## Returned file, 2026-11-24

The completed shared file came back on 2026-11-24. It is saved as `data/build/annotation/returned/annotation_returned_2026-11-24.xlsx`, and the sheets as they were before the merge are in `returned/backup_pre_merge/`. It was merged with:

```bash
uv run python -m medlabel_data.annotation.merge \
  ~/waicy-work/data/build/annotation/returned/annotation_returned_2026-11-24.xlsx \
  --alias <typo>=<name> --default-annotator 'pharmacist=pharmacist (licensed)' \
  --report ~/waicy-work/data/build/annotation/returned/merge_report.md
```

(One misspelt marker name was mapped with `--alias`; names are not published.)

A `--dry-run` came first. It found no invalid values and no conflicts. Running the merge again changes nothing.

Apart from the marks, Google Sheets changed two cells that merge doesn't read: a source URL on T6-03 became a link chip, and one `target` cell on the Training audit tab was blanked. The source sheets are unaffected.

**Who marked what.** The markers were members of the team, shown here as reviewers A, B and C, plus a licensed pharmacist. Nobody used AI tools, and nobody saw system outputs.

| Tab | Marked by | Rows marked |
|---|---|---|
| Markers – T5 | Reviewer A | 149 / 150 (T5-085 blank) |
| Markers – T3 | Reviewer C | 143 / 143 |
| Markers – T6 | Reviewer B | 30 / 30 |
| Markers – Training audit | Reviewer B | 23 / 23 |
| Markers – Decline check | Reviewer B | 20 / 20 |
| Second check | Reviewer B | 24 / 56 (all T5). The 21 T3, 5 T6 and 6 T5 rows were left blank. |
| Pharmacist | a licensed pharmacist (name cell left blank; recorded as `pharmacist (licensed)`) | 30 / 30 |
| Testers – usability | none yet | 0 sessions |

**Agreement:**
- **T5, first mark vs Second check** (reviewer A vs reviewer B): n = 24, 70.8% agreement, κ = 0.42. Both marked 11 as reworded and 6 as meaning changed. Reviewer B called 6 of reviewer A's "meaning changed" items reworded; 1 went the other way. No pair was marked by the same person.
- **Pharmacist vs T5 first mark** (reviewer A): n = 30, 86.7% agreement, κ = 0.68.
- **T3, T6:** none, because the Second check rows for them are blank.

**Caveats:**
- Reviewer A left `only_formatting` blank on every T5 row, so those marks give no formatting-only estimate.
- On the Second check, reviewer B answered `only_formatting` on 11 of 24 rows (8 y, 3 n).

The results per task are in [t3.md](t3.md), [t6.md](t6.md), [label-changes.md](label-changes.md) (Gate 3) and [data.md](data.md) (training audit and decline check).

## Optional: one file per person (`split`)

Not the main way any more, but kept for when separate files are wanted:

```bash
uv run python -m medlabel_data.annotation.split --annotators "Ana,Ben,Cy" --pharmacist "Dr Lee"
```

It writes `split/annotation_<name>.xlsx` in the same layout as the shared file, plus `split/assignments.csv` and `split/plan.json`. Each person's task tabs hold the rows they mark first, with `name` filled in. Their Second check tab holds the double-marked rows they mark second, so the two people never see each other's mark. The double-marked set is the same `double_set` as in the shared file. Rows are spread so everyone gets about the same number and the same mix of drugs: walking the drug-stratified order, each item goes to the least-loaded person, with ties broken by a seeded order of names. The pharmacist's file holds the Pharmacist tab only, and there is no testers tab. Options: `--tasks`, `--double T5=0.3`, `--seed`, `--due`. `merge` reads these files the same way.
