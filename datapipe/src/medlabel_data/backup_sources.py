"""Backup sources for questions the user's own label does not answer (docs/app.md, "Backup sources").

Writes two prebuilt files the app ships with:

* app/data/fda_food.json: sentences quoted from FDA consumer pages (U.S. government work,
  public domain), grouped by the active ingredients each passage names. Only ingredients the
  page names explicitly are listed; every sentence is checked against the live page text.
* app/data/ddinter_food.json: the DDInter 2.0 drug-food interaction table
  (ddinter2.scbdd.com, CC BY-NC-SA 4.0 per https://ddinter2.scbdd.com/terms/).

Run: uv run python -m medlabel_data.backup_sources
"""

from __future__ import annotations

import datetime as dt
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request

from . import http as fetch
from . import paths
from .sentences import split_sentences

FDA_JSON = paths.REPO / "app" / "data" / "fda_food.json"
DDINTER_JSON = paths.REPO / "app" / "data" / "ddinter_food.json"
DDINTER_RAW = paths.CACHE / "ddinter" / "food_interactions.json"

GRAPEFRUIT = "Grapefruit Juice and Some Drugs Don't Mix"
GF_INTRO = [
    "Grapefruit juice and grapefruit can affect the way your medicines work, and that food and drug interaction can be a concern.",
    "Here are examples of some types of drugs that grapefruit juice can cause problems (interact) with:",
]
GF_AFTER = [
    "Grapefruit juice does not affect all the drugs in the categories above.",
    "The severity of the interaction can be different depending on the person, the drug, and the amount of grapefruit juice you drink.",
]
GF_OTHER_FRUIT = [
    "Seville oranges (often used to make orange marmalade), pomelos, and tangelos (a cross between tangerines and grapefruit) might have the same effect as grapefruit juice.",
    "Do not eat those fruits if your medicine interacts with grapefruit juice.",
]


def _gf(item: str, *extra: list[str]) -> list[list]:
    out = [[GRAPEFRUIT, GF_INTRO + [item] + GF_AFTER]]
    out += [list(p) for p in extra]
    out.append(["Find Out if You Should Avoid Grapefruit or Other Juices", GF_OTHER_FRUIT])
    return out


FDA_PAGES = [
    {
        "id": "grapefruit",
        "title": GRAPEFRUIT,
        "url": "https://www.fda.gov/consumers/consumer-updates/grapefruit-juice-and-some-drugs-dont-mix",
        "content_date": "2021-07-01",
        "groups": [
            {"ingredients": ["simvastatin", "atorvastatin"], "passages": _gf(
                "Some statin drugs to lower cholesterol, such as Zocor (simvastatin) and Lipitor (atorvastatin).",
                ["How Grapefruit Juice Can Interfere With Medications", [
                    "For example, if you drink a lot of grapefruit juice while taking certain statin drugs to lower cholesterol, too much of the drug may stay in your body, increasing your risk for liver and muscle damage that can lead to kidney failure.",
                ]])},
            {"ingredients": ["nifedipine"], "passages": _gf(
                "Some drugs that treat high blood pressure, such as Procardia and Adalat CC (both nifedipine).")},
            {"ingredients": ["cyclosporine"], "passages": _gf(
                "Some organ-transplant rejection drugs, such as Neoral and Sandimmune capsule or oral solution (both cyclosporine).")},
            {"ingredients": ["buspirone"], "passages": _gf(
                "Some anti-anxiety drugs, such as BuSpar (buspirone).")},
            {"ingredients": ["budesonide"], "passages": _gf(
                "Some corticosteroids that treat Crohn\u2019s disease or ulcerative colitis, such as Entocort EC and Uceris tablet (both budesonide).")},
            {"ingredients": ["amiodarone"], "passages": _gf(
                "Some drugs that treat abnormal heart rhythms, such as Pacerone and Cordarone tablet (both amiodarone).")},
            {"ingredients": ["fexofenadine"], "passages": _gf(
                "Some antihistamines, such as Allegra (fexofenadine).",
                ["How Grapefruit Juice Can Interfere With Medications", [
                    "\u201cGrapefruit juice can cause less fexofenadine to enter the blood,\u201d decreasing how well the drug works, Huang says.",
                    "Fexofenadine may also not work as well if taken with orange or apple juice, so the drug label says, \u201cDo not take with fruit juices.\u201d",
                ]])},
        ],
    },
    {
        "id": "drug-interactions",
        "title": "Drug Interactions: What You Should Know",
        "url": "https://www.fda.gov/drugs/resources-drugs/drug-interactions-what-you-should-know",
        "content_date": "2013-09-25",
        "groups": [
            {"ingredients": ["acetaminophen", "aspirin", "ibuprofen", "ketoprofen", "magnesium salicylate", "naproxen"],
             "passages": [["Pain Relievers", [
                 "Ask a doctor before taking if you:",
                 "consume three or more alcohol-containing drinks per day",
                 "It is important to read the label of pain reliever products to learn about different drug interaction warnings for each ingredient.",
             ]]]},
            {"ingredients": ["caffeine"],
             "passages": [["Stimulants", [
                 "When using this product:",
                 "limit the use of foods, beverages, and other drugs that have caffeine.",
                 "Too much caffeine can cause nervousness, irritability, sleeplessness, and occasional rapid heart beat",
                 "be aware that the recommended dose of this product contains about as much caffeine as a cup of coffee",
             ]]]},
        ],
    },
]


def _norm(s: str) -> str:
    s = s.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def page_text(raw: bytes) -> str:
    t = raw.decode("utf-8", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return _norm(html.unescape(t))


def build_fda(today: str) -> dict:
    pages = []
    for p in FDA_PAGES:
        raw = fetch.get(p["url"], suffix=".html", use_cache=False)
        if raw is None:
            raise SystemExit(f"FDA page gone: {p['url']}")
        text = page_text(raw)
        for g in p["groups"]:
            for _, sents in g["passages"]:
                for s in sents:
                    if _norm(s) not in text:
                        raise SystemExit(f"Not on {p['url']}: {s!r}")
        pages.append({**p, "publisher": "U.S. Food and Drug Administration", "accessed": today})
    return {
        "note": "Sentences quoted verbatim from FDA consumer pages (U.S. government works, public domain). "
                "A group applies only to products whose active ingredients are all named in it.",
        "pages": pages,
    }


def _ddinter_session() -> tuple[urllib.request.OpenerDirector, str]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", fetch.USER_AGENT)]
    page = opener.open("https://ddinter2.scbdd.com/server/other_interaction/", timeout=60).read().decode()
    tok = re.search(r"csrfmiddlewaretoken: '([^']+)'", page)
    if not tok:
        raise SystemExit("DDInter page layout changed (no CSRF token).")
    return opener, tok.group(1)


def fetch_ddinter(page: int = 100) -> list[dict]:
    """All rows of the DDInter 2.0 drug-food table, via the site's own table endpoint (cached)."""
    if DDINTER_RAW.exists():
        return json.loads(DDINTER_RAW.read_text())
    opener, tok = _ddinter_session()
    rows: list[dict] = []
    total = None
    while total is None or len(rows) < total:
        body = urllib.parse.urlencode({
            "csrfmiddlewaretoken": tok, "draw": 1, "start": len(rows), "length": page,
            "search[value]": "", "severity": "", "mechanism": "",
        }).encode()
        req = urllib.request.Request(
            "https://ddinter2.scbdd.com/server/food-interaction-source/", data=body,
            headers={"Referer": "https://ddinter2.scbdd.com/server/other_interaction/", "X-Requested-With": "XMLHttpRequest"})
        j = json.loads(opener.open(req, timeout=60).read())
        total = j["recordsTotal"]
        if not j["data"]:
            break
        rows += j["data"]
        time.sleep(1.0)
    DDINTER_RAW.parent.mkdir(parents=True, exist_ok=True)
    DDINTER_RAW.write_text(json.dumps(rows, ensure_ascii=False))
    return rows


LEVEL = {"1": "Minor", "2": "Moderate", "3": "Major"}


def build_ddinter(today: str) -> dict:
    rows = []
    for r in fetch_ddinter():
        sents = []
        for field in ("newInteraction", "newManagement"):
            if r.get(field):
                sents += split_sentences(_norm(r[field]))
        if not sents:
            continue
        rows.append({
            "id": r["id"], "drug": r["drugName"], "food": r["foodName"],
            "level": LEVEL.get(str(r.get("level")), "Unknown"),
            "ddinter_id": r["internalID_a_id"], "sentences": sents,
        })
    rows.sort(key=lambda x: (x["drug"].lower(), x["food"].lower()))
    return {
        "source": "DDInter 2.0",
        "url": "https://ddinter2.scbdd.com/",
        "detail_url": "https://ddinter2.scbdd.com/server/drug-detail/{id}/",
        "license": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
        "terms_url": "https://ddinter2.scbdd.com/terms/",
        "citation": "Xiong G, et al. DDInter 2.0: an enhanced drug interaction resource with expanded data coverage, "
                    "new interaction types, and improved user interface. Nucleic Acids Research. 2025;53(D1):D1356-D1364.",
        "accessed": today,
        "note": "Drug-food rows from DDInter 2.0 (CC BY-NC-SA 4.0). Changes: text split into sentences, "
                "references and mechanism tags dropped. This file is shared under the same license.",
        "rows": rows,
    }


def main() -> None:
    today = dt.date.today().isoformat()
    FDA_JSON.parent.mkdir(parents=True, exist_ok=True)
    fda = build_fda(today)
    FDA_JSON.write_text(json.dumps(fda, ensure_ascii=False, indent=1))
    dd = build_ddinter(today)
    DDINTER_JSON.write_text(json.dumps(dd, ensure_ascii=False, separators=(",", ":")))
    n = sum(len(g["ingredients"]) for p in fda["pages"] for g in p["groups"])
    print(f"FDA: {len(fda['pages'])} pages, {n} ingredients -> {FDA_JSON}")
    print(f"DDInter: {len(dd['rows'])} rows, {len({r['drug'] for r in dd['rows']})} drugs -> {DDINTER_JSON} "
          f"({DDINTER_JSON.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
