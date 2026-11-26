"""Fetch the current openFDA record for each T2 (MedicationQA, DailyMed-sourced) set id, once.

    python3 train/scripts/final/t2_fetch.py   # -> final/t2/labels/<set_id>.json, final/t2/items.jsonl
Only items whose set id is current in openFDA can be loaded by the app; the rest are reported as excluded.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

B = Path("~/waicy-work/data/build").expanduser()
OUT = B / "final" / "t2"
rows = [json.loads(l) for l in open(B / "medqa" / "t2_dailymed.jsonl")]
got, miss = 0, []
for sid in sorted({r["set_id"] for r in rows if r["set_id"]}):
    p = OUT / "labels" / f"{sid}.json"
    if p.exists():
        got += 1
        continue
    url = "https://api.fda.gov/drug/label.json?" + urllib.parse.urlencode({"search": f'set_id:"{sid}"', "limit": "1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                res = json.load(r)["results"]
            p.write_text(json.dumps(res[0]))
            got += 1
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                miss.append(sid)
                break
            time.sleep(3)
        except Exception:
            time.sleep(3)
    else:
        miss.append(sid)
    time.sleep(0.3)
items = [r for r in rows if r["set_id"] and (OUT / "labels" / f"{r['set_id']}.json").exists()]
with open(OUT / "items.jsonl", "w") as f:
    for r in items:
        f.write(json.dumps(r) + "\n")
(OUT / "fetch.json").write_text(json.dumps({"labels": got, "not_found": miss, "items": len(items), "excluded_items": len(rows) - len(items),
                                            "fetched_at": time.strftime("%Y-%m-%d %H:%M")}, indent=1))
print(got, len(miss), len(items))
