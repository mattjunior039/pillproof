"""Fetch FDA labels: openFDA drug label API and DailyMed web services.

openFDA  https://open.fda.gov/apis/drug/label/  (current version of each label, JSON)
DailyMed https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm
         - /spls.json?drug_name=...       list SPL set ids for a drug
         - /spls/{setid}/history.json     every published version
         - /spls/{setid}/packaging.json   products and active ingredients
         - /getFile.cfm?setid=..&type=zip&version=N  zip with the SPL XML of version N
"""

import io
import json
import re
import urllib.parse
import zipfile

from . import http

OPENFDA = "https://api.fda.gov/drug/label.json"
DM = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
DM_FILE = "https://dailymed.nlm.nih.gov/dailymed/getFile.cfm"


# ---------- openFDA ----------

def openfda_search(search: str, limit: int = 100, skip: int = 0) -> list[dict]:
    q = urllib.parse.urlencode({"search": search, "limit": limit, "skip": skip})
    d = http.get_json(f"{OPENFDA}?{q}")
    return [] if d is None else d.get("results", [])


def openfda_by_set_ids(set_ids: list[str], batch: int = 50) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(set_ids), batch):
        part = set_ids[i : i + batch]
        search = "set_id:(" + " ".join(f'"{s}"' for s in part) + ")"
        for r in openfda_search(search, limit=len(part)):
            out[r["set_id"]] = r
    return out


def openfda_by_ingredient(ingredient: str, limit: int = 100) -> list[dict]:
    """All current labels whose openFDA substance or generic name matches (exact phrase)."""
    results = []
    s = f'openfda.substance_name.exact:"{ingredient.upper()}"'
    while True:
        page = openfda_search(s, limit=limit, skip=len(results))
        results += page
        if len(page) < limit or len(results) >= 1000:
            return results


# ---------- DailyMed ----------

def _paged(url: str) -> list[dict]:
    out, page = [], 1
    while True:
        sep = "&" if "?" in url else "?"
        d = http.get_json(f"{url}{sep}pagesize=100&page={page}")
        if d is None:
            return out
        out += d.get("data", [])
        meta = d.get("metadata", {})
        if int(meta.get("current_page", 1)) >= int(meta.get("total_pages", 1)):
            return out
        page += 1


def dailymed_spls_for_drug(drug_name: str) -> list[dict]:
    return _paged(f"{DM}/spls.json?" + urllib.parse.urlencode({"drug_name": drug_name}))


def dailymed_history(set_id: str) -> list[dict]:
    """[{spl_version, published_date}, ...], newest first."""
    d = http.get_json(f"{DM}/spls/{set_id}/history.json?pagesize=100")
    if d is None:
        return []
    hist = d["data"]["history"]
    meta = d.get("metadata", {})
    if int(meta.get("total_pages", 1)) > 1:
        hist = []
        for row in _paged(f"{DM}/spls/{set_id}/history.json"):
            hist += row.get("history", []) if isinstance(row, dict) and "history" in row else [row]
    return hist


def dailymed_packaging(set_id: str) -> dict | None:
    d = http.get_json(f"{DM}/spls/{set_id}/packaging.json")
    return None if d is None or not d.get("data", {}).get("setid") else d["data"]


def dailymed_spl_xml(set_id: str, version: int | None = None, use_cache: bool = True) -> bytes | None:
    """SPL XML for a given version (latest if version is None)."""
    params = {"setid": set_id, "type": "zip"}
    if version is not None:
        params["version"] = str(version)
    data = http.get(f"{DM_FILE}?" + urllib.parse.urlencode(params), suffix=".zip", use_cache=use_cache)
    if data is None or not data.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if not xmls:
            return None
        return z.read(xmls[0])


# ---------- ingredients ----------

_SALT_WORDS = {
    "hydrochloride", "hcl", "dihydrochloride", "hydrobromide", "besylate", "besilate", "mesylate",
    "maleate", "fumarate", "succinate", "tartrate", "bitartrate", "citrate", "sulfate", "bisulfate",
    "phosphate", "acetate", "sodium", "potassium", "calcium", "magnesium", "monohydrate",
    "dihydrate", "trihydrate", "hemihydrate", "sesquihydrate", "anhydrous", "hyclate", "lactate",
    "gluconate", "medoxomil", "dipropionate", "propionate", "valerate", "furoate", "bromide",
    "chloride", "nitrate", "oxalate", "pamoate", "tosylate", "malate", "mononitrate", "disodium",
    "trisodium", "dimesylate", "estolate", "stearate", "ethylsuccinate", "usp", "er", "xr",
    "embonate", "napsylate", "axetil", "pivoxil", "dipivoxil", "teoclate", "carbonate", "hemifumarate",
    "erbumine", "olamine", "tromethamine", "meglumine", "decanoate", "enanthate", "cypionate",
    "aspartate", "saccharate", "benzoate", "dl", "disoproxil", "alafenamide", "ethyl", "hydrate",
}


def base_ingredient(name: str) -> str:
    """Strip salt and hydrate words: 'AMLODIPINE BESYLATE' -> 'amlodipine'.

    If stripping would leave nothing (e.g. 'CALCIUM CARBONATE'), the name is kept as is.
    Over-merging is acceptable for split purposes; it only makes groups larger.
    """
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    kept = [w for w in words if w not in _SALT_WORDS]
    return " ".join(kept or words)


def label_ingredients(openfda_record: dict | None, packaging: dict | None) -> list[str]:
    names: list[str] = []
    if openfda_record:
        names = openfda_record.get("openfda", {}).get("substance_name", []) or []
    if not names and packaging:
        for p in packaging.get("products", []):
            names += [a["name"] for a in p.get("active_ingredients", [])]
    return sorted({base_ingredient(n) for n in names if n.strip()})


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
