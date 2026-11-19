# Annotation workbook

All human review work is in one workbook that opens in Google Sheets. It can be split into one file per person, and the marks are merged back into the original sheets. The code is in `datapipe/src/medlabel_data/annotation/`. The outputs are in `data/build/annotation/` and are not in git.

## Tabs

| tab | items | source sheet (marks are merged back here) | reviewer fills in |
|---|---|---|---|
| Start here | – | – | read: the rule, then for each task what to do, 2 worked examples and the time per item |
| Assignments | – | – | nothing; `done` and `remaining` are formulas that count filled marks |
| T5 label changes | 150 | `changes/t5/t5_sheet.csv` | `mark` (meaning changed / reworded), `only_formatting` (y / n), `notes` |
| T3 questions | 143 | `t3/t3_draft.csv` | `user_status` (keep / edit / drop), `user_notes` |
| T6 questions | 30 | `t6/t6_draft.csv` | `user_status` (keep / edit / drop), `user_notes` |
| Training audit | 23 | `fdarx/audit/audit_review_20.csv` | `user_verdict` (ok / wrong_sentences / wrong_answer / should_decline / should_answer / bad_question), `user_notes` |
| Decline check | 20 | `fdarx/audit/decline_review_20.csv` | `user_verdict` (not_in_label / answerable_elsewhere / partly / bad_question), `user_where_found`, `user_notes` |
| Pharmacist | 30 | `changes/t5/pharmacist_sheet.csv` | same as T5; expert only |
| Decline labels | 8,639 lines | `fdarx/audit/decline_check_labels/` | nothing; the label text for the decline check, one row per line (filter on `item_id`) |

Every task row has:
- a stable `item_id`: `T5-001`, `T3-001`, `T6-01`, `AUD-001`, `DEC-02`, and `PH-T5-004` for pharmacist rows;
- `task`;
- an `annotator` dropdown;
- the fields the reviewer needs;
- the mark columns, which are shaded and darker in the header.

Each task has its own colour. The header is frozen, text wraps, and choice columns have dropdowns (list data validation). These survive an `.xlsx` import into Google Sheets.

The Pharmacist tab holds a subset of T5: the 30 rows have the same `t5_id` as their T5 rows. A pharmacist marks them independently, and they are compared with the T5 marks. The `plain_language_*` columns of `pharmacist_sheet.csv` are left out because they would show model output. Checking the plain-language rewrites is a separate, later step.

## Kept blind

The rule shown first is: *humans only, no AI tools, and don't look up the app's answers*.

The workbook never shows:
- AI verdicts or notes (`ai_*`);
- `t5_key_hidden`;
- `r3_status`;
- the decline-check `check_coverage`;
- support-check coverage numbers inside the T3/T6 evidence notes;
- any score, prediction or model output.

`tasks.BLOCKED` is checked on every header that is written, and writing fails if a blocked column would be shown. AI notes are joined back only after merging, from the original sheets.

The training-audit rows show what the model was trained on: the `sentences_shown`, the `target`, and the original line from the benchmark. They are training data, not model outputs.

## Commands

Run from `datapipe/`:

```bash
uv run python -m medlabel_data.annotation.build                      # master only
uv run python -m medlabel_data.annotation.split --annotators "Ana,Ben,Cy" --pharmacist "Dr Lee"
uv run python -m medlabel_data.annotation.merge ~/waicy-work/data/build/annotation/split --dry-run
uv run python -m medlabel_data.annotation.merge ~/waicy-work/data/build/annotation/split
```

### build

`build` writes `annotation_master.xlsx` and `csv/NN_<tab>.csv`, one file per tab. The Assignments tab then has one `all` row per task.

### split

`split` writes the following to `split/`:
- `annotation_<name>.xlsx` for each person. Each file has only that person's rows, with `annotator` filled in, their Assignments rows with live counts, the Start here rows for their tasks, and the decline-label lines for their decline items.
- `annotation_<pharmacist>.xlsx` with the Pharmacist tab only.
- `assignments.csv` (item_id, task, annotator, double) and `plan.json` (seed and settings).

It also rebuilds the master with the plan. In the master, the `annotator` column stays empty; people pick their name if they work there. The live counts are in each person's file.

Options:
- `--tasks T5,T3`: split only some tasks.
- `--double T5=0.3`: change the double-marked shares.
- `--seed` and `--due`.

### merge

`merge` reads the completed files. These can be:
- per-person workbooks;
- the master downloaded from Google Sheets as `.xlsx`;
- tab CSVs.

It accepts files or folders; folders are not searched recursively. It writes `merge_report.md`.

## How the work is split

The seed is fixed: `2026` by default. The split is deterministic for the same names, seed and sheets.

For each task:
1. Items are grouped by drug, with drugs in sorted order.
2. Within each drug, items are shuffled with `random.Random(f"{seed}:{task}:{drug}")`.
3. Walking that order, each item goes to the least-loaded annotator. Ties are broken by a seeded per-task order of names. So everyone gets about the same number of items and the same mix of drugs.

**Double-marked items:**
- The shares are T5 20%, T3 15% and T6 15%. The audit and decline check have none, because the student reviews them.
- k = share × N, rounded half up. The double-marked items are a systematic sample of the walking order, at positions ⌊i·N/k⌋, so they are spread over the drugs.
- Each double gets a second, different annotator: the least-loaded one.
- The two people each have the row in their own file and never see each other's mark.
- With one annotator, nothing is double-marked.

With Ana, Ben and Cy, the split gives:
- T5: 60 items each, 30 double-marked;
- T3: 54–55 each, 21 double-marked;
- T6: 11–12 each, 5 double-marked;
- audit: 7–8 each;
- decline: 6–7 each.

## How marks are merged back

**Reading:**
- Every tab whose header has `item_id` and `task` is read.
- Choice values are matched ignoring case, spaces and underscores. Invalid values are reported and ignored.
- These are reported as warnings:
  - rows left blank, per task and annotator;
  - rows with notes but no main mark;
  - unknown item ids;
  - marks by someone who was not assigned that item, if `split/assignments.csv` exists.
- Rows with marks but no annotator are skipped with a warning, unless `--default-annotator NAME` is given.
- The same person giving different marks for the same item in two files is an error.

**Writing:**
- Marks go into the task's source sheet. The sheet gets an `annotator` column. For a second annotator of a double-marked item, it gets `annotator_2` and `<mark>_2` (for example `mark_2`, `user_status_2`).
- A person always goes back to the same slot.
- Existing marks are never overwritten. Every conflict is listed, and then the whole merge is aborted with nothing written.
- Equal values are fine, so merging the same files twice is safe.
- If a sheet already has marks with no annotator name (filled in by hand):
  - if they match the incoming marks, they are attributed to that person;
  - if not, they are kept as a separate mark, with a warning.

**Agreement:**
- For each task, Cohen's kappa and percent agreement are computed over the double-marked items, on the main mark.
- Pairs are pooled per task (first vs second mark), whoever the two annotators were.
- The pharmacist's `mark` is compared with the first T5 mark for the same `t5_id`.

The T3 and T6 builders keep extra columns such as `annotator` and `*_2` when they rebuild their sheets (`t3.write_sheet`). The T5 sheet generator is on another branch and does not yet keep them. Rebuilding `t5_sheet.csv` after a merge would drop the merged marks, so merge only after T5 is final, or back the sheet up first.

## Google Sheets

1. Upload the `.xlsx` (master or a person's file) to Drive and open it with Google Sheets. Alternatively, use File → Import → Upload.
2. Share each person's file only with that person.
3. When everyone is done, download each file as `.xlsx` (File → Download → Microsoft Excel) into a folder, then run `merge` on that folder. Start with `--dry-run`.
