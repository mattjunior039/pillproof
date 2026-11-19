import csv
from collections import Counter

import pytest
from openpyxl import load_workbook

from medlabel_data.annotation import merge, workbook
from medlabel_data.annotation.split import assign, make_plan, summary
from medlabel_data.annotation.tasks import Mark, Task


def make_task(tmp_path, n=12, key="T5", double=0.25, rows=None):
    src = tmp_path / f"{key}.csv"
    rows = rows or [{"id": f"X-{i:03d}", "drug": f"drug{i % 4}", "text": f"sentence {i}", "mark": "", "notes": ""}
                    for i in range(1, n + 1)]
    with open(src, "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    t = Task(key, f"{key} tab", src, lambda r: r["id"], [("drug", 10), ("text", 30)],
             [Mark("mark", ["meaning changed", "reworded"]), Mark("notes")], "C9DAF8", "1 min", "Mark it.",
             ("e1", "e2"), double=double)
    return t, src


def read(src):
    with open(src, newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def fill(path, values):
    """values: item_id -> mark, written into the person's workbook like a reviewer would."""
    wb = load_workbook(path)
    ws = wb["T5 tab"]
    hdr = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[0].value in values:
            row[hdr.index("mark")].value = values[row[0].value]
    wb.save(path)


def test_assign_balanced_stratified_deterministic():
    items = [{"item_id": f"X-{i:03d}", "drug": f"d{i % 6}"} for i in range(150)]
    out = assign(items, ["A", "B", "C"], seed=7, double=0.2, key="T5")
    assert out == assign(items, ["A", "B", "C"], seed=7, double=0.2, key="T5")
    assert out != assign(items, ["A", "B", "C"], seed=8, double=0.2, key="T5")
    doubles = [w for w in out.values() if len(w) == 2]
    assert len(doubles) == 30 and all(a != b for a, b in doubles)
    load = Counter(a for w in out.values() for a in w)
    assert max(load.values()) - min(load.values()) <= 1
    drug = {it["item_id"]: it["drug"] for it in items}
    for a in "ABC":
        assert len({drug[i] for i, w in out.items() if a in w}) == 6
    assert Counter(drug[i] for i, w in out.items() if len(w) == 2).most_common(1)[0][1] <= 6
    assert all(len(w) == 1 for w in assign(items, ["A"], double=0.2).values())


def test_split_write_fill_merge_roundtrip(tmp_path):
    t, src = make_task(tmp_path)
    items = {"T5": t.load()}
    plan = make_plan(items, [t], ["A", "B"], None, seed=1)
    for name in "AB":
        mine = {p["item_id"] for p in plan if p["annotator"] == name}
        rows = {"T5": [{**it, "annotator": name} for it in items["T5"] if it["item_id"] in mine]}
        workbook.write(tmp_path / f"{name}.xlsx", [t], rows, [name], summary(plan, [t], name))
        fill(tmp_path / f"{name}.xlsx", {i: "reworded" for i in mine})
    res = merge.read_marks([tmp_path / "A.xlsx", tmp_path / "B.xlsx"], {"T5": t})
    sheets = merge.apply(res, {"T5": t})
    assert not res.errors
    cols, rows = sheets[src]
    assert {"annotator", "mark", "annotator_2", "mark_2"} <= set(cols)
    doubled = [r for r in rows if r["annotator_2"]]
    assert len(doubled) == 3 and all(r["annotator"] != r["annotator_2"] and r["mark_2"] == "reworded" for r in doubled)
    assert all(r["mark"] == "reworded" and r["annotator"] in "AB" for r in rows)
    agree = merge.agreement(sheets, {"T5": t})
    assert agree[0]["n"] == 3 and agree[0]["agree"] == 1.0


def test_merge_refuses_to_overwrite_and_warns(tmp_path):
    rows = [{"id": "X-001", "drug": "d", "text": "s", "mark": "reworded", "notes": "", "annotator": "A"},
            {"id": "X-002", "drug": "d", "text": "s", "mark": "", "notes": "", "annotator": ""},
            {"id": "X-003", "drug": "d", "text": "s", "mark": "", "notes": "", "annotator": ""}]
    t, src = make_task(tmp_path, rows=rows)
    sub = tmp_path / "in.csv"
    sub.write_text("item_id,task,annotator,mark,notes\n"
                   "X-001,T5,A,meaning changed,\n"   # A changed their mind: refuse
                   "X-002,T5,A,Reworded,\n"          # case-insensitive choice
                   "X-003,T5,A,maybe,\n"             # invalid
                   "X-009,T5,A,reworded,\n"          # unknown item
                   "X-002,T5,,,\n")                  # blank row
    before = src.read_text()
    res = merge.read_marks([sub], {"T5": t})
    sheets = merge.apply(res, {"T5": t})
    assert any("refusing to overwrite" in e for e in res.errors)
    assert any("invalid mark 'maybe'" in w for w in res.warnings)
    assert any("unknown item_id 'X-009'" in w for w in res.warnings)
    assert any("left blank" in w for w in res.warnings)
    assert sheets[src][1][1]["mark"] == "reworded"
    assert src.read_text() == before  # apply works in memory; main writes nothing when there are errors


def test_same_mark_from_two_files_is_fine_but_different_is_an_error(tmp_path):
    t, _ = make_task(tmp_path)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("item_id,task,annotator,mark\nX-001,T5,A,reworded\n")
    b.write_text("item_id,task,annotator,mark\nX-001,T5,A,reworded\n")
    assert not merge.read_marks([a, b], {"T5": t}).errors
    b.write_text("item_id,task,annotator,mark\nX-001,T5,A,meaning changed\n")
    assert merge.read_marks([a, b], {"T5": t}).errors


def test_kappa_known_value():
    k, po, n = merge.kappa([("a", "a"), ("a", "a"), ("b", "b"), ("a", "b")])
    assert (round(k, 3), po, n) == (0.5, 0.75, 4)
    assert merge.kappa([("a", "a")])[0] is None


def test_workbook_blocks_hidden_columns(tmp_path):
    t, _ = make_task(tmp_path)
    t.show = t.show + [("ai_verdict", 10)]
    with pytest.raises(ValueError, match="ai_verdict"):
        workbook.write(tmp_path / "x.xlsx", [t], {"T5": t.load()}, ["A"])


def test_workbook_has_dropdowns_and_frozen_header(tmp_path):
    t, _ = make_task(tmp_path)
    workbook.write(tmp_path / "m.xlsx", [t], {"T5": t.load()}, ["A", "B"], csv_dir=tmp_path / "csv")
    ws = load_workbook(tmp_path / "m.xlsx")["T5 tab"]
    assert ws.freeze_panes == "B2"
    assert {dv.formula1 for dv in ws.data_validations.dataValidation} == {'"A,B"', '"meaning changed,reworded"'}
    assert sorted(p.name for p in (tmp_path / "csv").iterdir()) == ["01_start_here.csv", "02_assignments.csv",
                                                                     "03_t5_tab.csv"]
