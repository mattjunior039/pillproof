import csv
from collections import Counter

import pytest
from openpyxl import load_workbook

from medlabel_data.annotation import merge, usability, workbook
from medlabel_data.annotation.split import assign, double_set, make_plan, write_person
from medlabel_data.annotation.tasks import Mark, Task, read_csv


def make_task(tmp_path, n=12, key="T5", double=0.25, rows=None):
    src = tmp_path / f"{key}.csv"
    rows = rows or [{"id": f"X-{i:03d}", "drug": f"drug{i % 4}", "text": f"sentence {i}", "mark": "", "notes": ""}
                    for i in range(1, n + 1)]
    with open(src, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    t = Task(key, f"{key} tab", src, lambda r: r["id"], [("drug", 10), ("text", 30)],
             [Mark("mark", ["meaning changed", "reworded"]), Mark("only_formatting", ["y", "n"]), Mark("notes")],
             "markers", (1, 1), "Mark it.", ("e1", "e2"), double=double)
    return t, src


def master(tmp_path, t, sessions=2):
    items = {t.key: t.load()}
    ids = {t.key: double_set(items[t.key], 1, t.double, t.key)}
    path = tmp_path / "master.xlsx"
    workbook.write(path, [t], items, workbook.second_rows([t], items, ids), sessions, csv_dir=tmp_path / "csv")
    return path, ids[t.key]


def fill(path, tab, values, header_row=2):
    """values: item_id -> {column: value}, typed in like a reviewer would."""
    wb = load_workbook(path)
    ws = wb[tab]
    hdr = [c.value for c in ws[header_row]]
    for row in ws.iter_rows(min_row=header_row + 1):
        for c, v in values.get(row[0].value, {}).items():
            row[hdr.index(c)].value = v
    wb.save(path)


def test_assign_balanced_stratified_deterministic():
    items = [{"item_id": f"X-{i:03d}", "drug": f"d{i % 6}"} for i in range(150)]
    out = assign(items, ["A", "B", "C"], seed=7, double=0.2, key="T5")
    assert out == assign(items, ["A", "B", "C"], seed=7, double=0.2, key="T5")
    assert out != assign(items, ["A", "B", "C"], seed=8, double=0.2, key="T5")
    doubles = [w for w in out.values() if len(w) == 2]
    assert len(doubles) == 30 and all(a != b for a, b in doubles)
    assert {i for i, w in out.items() if len(w) == 2} == set(double_set(items, 7, 0.2, "T5"))
    load = Counter(a for w in out.values() for a in w)
    assert max(load.values()) - min(load.values()) <= 1
    drug = {it["item_id"]: it["drug"] for it in items}
    for a in "ABC":
        assert len({drug[i] for i, w in out.items() if a in w}) == 6
    assert Counter(drug[i] for i, w in out.items() if len(w) == 2).most_common(1)[0][1] <= 6
    assert all(len(w) == 1 for w in assign(items, ["A"], double=0.2).values())


def test_shared_file_layout(tmp_path):
    t, _ = make_task(tmp_path)
    path, doubles = master(tmp_path, t)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Start here", "Progress", "T5 tab", "Second check", "Testers – usability"]
    ws = wb["T5 tab"]
    hdr = [c.value for c in ws[2]]
    assert ws["A1"].value.startswith("What to do") and ws.freeze_panes == "A3"
    assert hdr == ["item_id", "drug", "text", "name", "mark", "only_formatting", "notes", "task"]
    dvs = {str(dv.sqref): dv.formula1 for dv in ws.data_validations.dataValidation}
    assert dvs == {"E3:E14": '"meaning changed,reworded"', "F3:F14": '"y,n"'}  # name is free text
    sc = wb["Second check"]
    assert [c.value for c in sc[2]][:5] == ["item_id", "drug", "item", "name", "answer"]
    assert [sc.cell(row=r, column=1).value for r in range(3, 6)] == doubles and sc.max_row == 5
    assert all(c.value is None for c in sc[3][3:7])
    prog = wb["Progress"]
    assert prog["C3"].value == "=COUNTA('T5 tab'!$E$3:$E$14)"
    assert prog["A4"].value == "Second check" and "COUNTIFS" in prog["B9"].value
    u = wb["Testers – usability"]
    assert u.freeze_panes == "A4" and u["A4"].value == "U-01" and u.max_row == 5
    assert sorted(p.name for p in (tmp_path / "csv").iterdir())[:3] == ["01_start_here.csv", "02_progress.csv",
                                                                        "03_t5_tab.csv"]


def test_fill_shared_file_and_merge_roundtrip(tmp_path):
    t, src = make_task(tmp_path)
    path, doubles = master(tmp_path, t)
    fill(path, "T5 tab", {f"X-{i:03d}": {"name": "Ana" if i < 7 else "Ben", "mark": "reworded"} for i in range(1, 12)})
    fill(path, "Second check", {doubles[0]: {"name": "Cy", "answer": "Reworded"},
                                doubles[1]: {"name": "Cy", "answer": "meaning changed", "notes": "dose"},
                                doubles[2]: {"name": "Cy", "answer": "reworded", "only_formatting": "y"}})
    sus = {f"sus_{i}": 5 if i % 2 else 1 for i in range(1, 11)}
    fill(path, "Testers – usability", {"U-01": {"name": "Ana", "tester": "T1", "age_band": "70-79",
                                                "voice_done": "with help", "voice_minutes": 2.0, **sus}}, 3)
    out = tmp_path / "usability.csv"
    res, text = merge.merge([path], {"T5": t}, out)
    assert not res.errors, res.errors
    rows = {r["id"]: r for r in read_csv(src)}
    assert rows["X-001"]["annotator"] == "Ana" and rows["X-001"]["mark"] == "reworded"
    assert rows[doubles[1]]["annotator_2"] == "Cy" and rows[doubles[1]]["notes_2"] == "dose"
    assert rows[doubles[2]]["only_formatting_2"] == "y"
    assert any("1 row(s) left blank" in w for w in res.warnings)  # X-012
    (s,) = read_csv(out)
    assert (s["item_id"], s["age_band"], s["voice_minutes"], s["sus_score"]) == ("U-01", "70-79", "2", "100")
    assert "mean SUS 100.0" in text and "T5: first vs Second check" in text

    # running it again is a no-op; a changed mark is refused and nothing is written
    assert not merge.merge([path], {"T5": t}, out)[0].errors
    fill(path, "T5 tab", {"X-001": {"mark": "meaning changed"}})
    before = src.read_text()
    res, _ = merge.merge([path], {"T5": t}, out)
    assert any("refusing to overwrite" in e for e in res.errors) and src.read_text() == before


def test_merge_warnings_from_csv_with_what_to_do_row(tmp_path):
    t, _ = make_task(tmp_path)
    sub = tmp_path / "in.csv"
    sub.write_text("What to do: mark it,,,,\n"
                   "item_id,task,name,mark,notes\n"
                   "X-002,T5,A,Reworded,\n"          # case-insensitive choice
                   "X-003,T5,A,maybe,\n"             # invalid
                   "X-099,T5,A,reworded,\n"          # unknown item
                   "X-004,T5,,reworded,\n"           # no name
                   "X-005,T5,A,,a note\n")           # note without a mark
    res = merge.read_marks([sub], {"T5": t})
    assert res.marks == {("T5", "X-002", 1): {"annotator": "A", "mark": "reworded"},
                         ("T5", "X-005", 1): {"annotator": "A", "notes": "a note"}}
    w = "\n".join(res.warnings)
    assert "invalid mark 'maybe'" in w and "unknown item_id 'X-099'" in w and "no name" in w
    assert "mark is blank but other columns are filled" in w


def test_same_mark_from_two_files_is_fine_but_different_is_an_error(tmp_path):
    t, _ = make_task(tmp_path)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("item_id,task,name,mark\nX-001,T5,A,reworded\n")
    b.write_text("item_id,task,name,mark\nX-001,T5,A,reworded\n")
    assert not merge.read_marks([a, b], {"T5": t}).errors
    b.write_text("item_id,task,name,mark\nX-001,T5,A,meaning changed\n")
    assert merge.read_marks([a, b], {"T5": t}).errors


def test_kappa_known_value_and_same_person_pairs_left_out(tmp_path):
    k, po, n = merge.kappa([("a", "a"), ("a", "a"), ("b", "b"), ("a", "b")])
    assert (round(k, 3), po, n) == (0.5, 0.75, 4)
    assert merge.kappa([("a", "a")])[0] is None
    t, src = make_task(tmp_path)
    rows = [{"annotator": "A", "mark": "reworded", "annotator_2": a2, "mark_2": "reworded", "id": i}
            for i, a2 in (("X-1", "B"), ("X-2", "a"))]
    warn = []
    (a,) = merge.agreement({src: ([], rows)}, {"T5": t}, warn)
    assert a["n"] == 1 and "X-2" in warn[0]


def test_name_aliases_and_per_task_default(tmp_path):
    t, _ = make_task(tmp_path)
    p, _ = make_task(tmp_path, key="pharmacist")
    sub = tmp_path / "in.csv"
    sub.write_text("item_id,task,name,mark\n"
                   "X-001,T5,albet ,reworded\n"
                   "X-002,T5,Al  bert,reworded\n"
                   "X-003,T5,,reworded\n"
                   "X-001,pharmacist,,reworded\n")
    res = merge.read_marks([sub], {"T5": t, "pharmacist": p}, {"pharmacist": "pharmacist (licensed)"},
                           {"Albet": "Albert"})
    who = {(k, i): v["annotator"] for (k, i, _), v in res.marks.items()}
    assert who == {("T5", "X-001"): "Albert", ("T5", "X-002"): "Al bert",
                   ("pharmacist", "X-001"): "pharmacist (licensed)"}
    assert any("X-003: marks but no name" in w for w in res.warnings)


def test_sus_score():
    assert usability.sus_score({f"sus_{i}": "3" for i in range(1, 11)}) == "50"
    assert usability.sus_score({f"sus_{i}": "5" if i % 2 else "1" for i in range(1, 11)}) == "100"
    assert usability.sus_score({"sus_1": "3"}) == ""


def test_split_person_file_hides_other_mark(tmp_path):
    t, _ = make_task(tmp_path)
    items = {"T5": t.load()}
    plan = make_plan(items, [t], ["A", "B"], None, seed=1)
    write_person(tmp_path / "A.xlsx", "A", [t], items, plan)
    wb = load_workbook(tmp_path / "A.xlsx")
    main_ids = {r[0] for r in wb["T5 tab"].iter_rows(min_row=3, values_only=True)}
    second_ids = {r[0] for r in wb["Second check"].iter_rows(min_row=3, values_only=True)} \
        if "Second check" in wb.sheetnames else set()
    assert not main_ids & second_ids
    first = {p["item_id"] for p in plan if p["annotator"] == "A"}
    assert main_ids | second_ids == first
    assert all(r[3] == "A" for r in wb["T5 tab"].iter_rows(min_row=3, values_only=True))


def test_workbook_blocks_hidden_columns(tmp_path):
    t, _ = make_task(tmp_path)
    t.show = t.show + [("ai_verdict", 10)]
    with pytest.raises(ValueError, match="ai_verdict"):
        workbook.write(tmp_path / "x.xlsx", [t], {"T5": t.load()})
