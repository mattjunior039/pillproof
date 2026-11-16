"""Fetch every published version of the FDA labels for the T3/T5 drug list.

Steps for each drug in config/t3_drugs.json:
1. Resolve one label (SPL set id) via openFDA. Preference order: the original packager
   (not a repackager), then an NDA (brand) application if a brand is given, then the
   highest current SPL version number (a proxy for the longest history).
   A `set_id` already present in the config is used as is, so choices can be pinned.
2. List versions with DailyMed `history.json`.
3. Download each version's SPL XML (stored gzipped) and parse it into sections and
   sentences (stored as JSON).

Layout: LABELS/<slug>/<set_id>/v0007.xml.gz, v0007.json, and LABELS/<slug>/manifest.json.

Usage (from datapipe/):
  uv run python -m medlabel_data.labelfetch --resolve-only      # write the chosen set ids
  uv run python -m medlabel_data.labelfetch --only atorvastatin  # fetch one drug
  uv run python -m medlabel_data.labelfetch                      # fetch all (after confirmation)
"""

import argparse
import gzip
import json
import re
import sys

from . import labels, paths
from .spl import parse_spl

DRUGS_CONFIG = paths.CONFIG / "t3_drugs.json"
RX = "HUMAN PRESCRIPTION DRUG"
# Relabelers/repackagers seen in DailyMed titles; their copies lag the manufacturer's label.
REPACKAGERS = re.compile(
    r"a-s medication|aphena|cardinal health|redpharm|proficient rx|remedyrepack|bryant ranch|nucare|"
    r"preferred pharmaceuticals|quality care|direct[_ ]?rx|pd-rx|henry schein|lake erie|denton|northwind|"
    r"st\. mary|asclemed|enovachem|medsource|rebel distributors|unit dose services|american health packaging|"
    r"golden state medical|aidarex|physicians total care|readymeds|blenheim|coupler|med-health|"
    r"lifestar|stat rx|clinical solutions wholesale|advanced rx|hj harkins|marlex|safecor|aphena", re.I)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def candidates(drug: dict, use_brand: bool = True) -> list[dict]:
    q = f'openfda.generic_name:"{drug["ingredient"]}" AND openfda.product_type:"{RX}" AND openfda.route:"ORAL"'
    if use_brand and drug.get("brand"):
        q += f' AND openfda.brand_name:"{drug["brand"]}"'
    want = labels.base_ingredient(drug["ingredient"])
    exclude = re.compile(drug["exclude"], re.I) if drug.get("exclude") else None
    keep = []
    for r in labels.openfda_search(q, limit=100):
        o = r.get("openfda", {})
        subs = o.get("substance_name", [])
        names = " ".join(o.get("brand_name", []) + o.get("generic_name", []))
        if len(subs) == 1 and labels.base_ingredient(subs[0]) == want and not (exclude and exclude.search(names)):
            keep.append(r)
    return keep


def rank_key(r: dict, brand: str | None) -> tuple:
    o = r.get("openfda", {})
    original = bool(o.get("is_original_packager") and o["is_original_packager"][0])
    nda = any(a.startswith(("NDA", "BLA")) for a in o.get("application_number", []))
    return (original, nda if brand else False, int(r.get("version") or 0))


def _dailymed_brand(drug: dict) -> dict | None:
    """Highest-version DailyMed label whose title starts with the brand name (openFDA can lag)."""
    exclude = re.compile(drug["exclude"], re.I) if drug.get("exclude") else None
    brand = drug["brand"].upper()
    rows = [r for r in labels.dailymed_spls_for_drug(drug["brand"])
            if r.get("title", "").upper().startswith(brand + " ") and not REPACKAGERS.search(r["title"])
            and not (exclude and exclude.search(r["title"]))]
    return max(rows, key=lambda r: int(r["spl_version"]), default=None)


def resolve(drug: dict) -> dict:
    if drug.get("set_id"):
        recs = labels.openfda_by_set_ids([drug["set_id"]])
        r = recs.get(drug["set_id"])
        return {"set_id": drug["set_id"], "source": "pinned",
                "manufacturer": (r or {}).get("openfda", {}).get("manufacturer_name", [None])[0],
                "current_version": (r or {}).get("version")}
    cands = candidates(drug)
    best = max(cands, key=lambda r: rank_key(r, drug.get("brand")), default=None)
    brand_fallback = False
    if best is None and drug.get("brand"):
        cands, brand_fallback = candidates(drug, use_brand=False), True
        best = max(cands, key=lambda r: rank_key(r, None), default=None)
    is_orig = bool(best and best.get("openfda", {}).get("is_original_packager"))
    if drug.get("brand") and (brand_fallback or not is_orig):
        dm = _dailymed_brand(drug)
        if dm and (best is None or int(dm["spl_version"]) > int(best.get("version") or 0)):
            return {"set_id": dm["setid"], "source": "dailymed_brand", "title": dm["title"],
                    "current_version": dm["spl_version"], "published_date": dm.get("published_date")}
    if best is None:
        return {"set_id": None, "error": "no candidates"}
    o = best.get("openfda", {})
    return {
        "set_id": best["set_id"], "source": "openfda_generic" if brand_fallback or not drug.get("brand") else "openfda_brand",
        "n_candidates": len(cands), "brand_not_found": brand_fallback,
        "manufacturer": (o.get("manufacturer_name") or [None])[0],
        "brand_name": (o.get("brand_name") or [None])[0],
        "application_number": (o.get("application_number") or [None])[0],
        "original_packager": bool(o.get("is_original_packager")),
        "current_version": best.get("version"), "effective_time": best.get("effective_time"),
    }


def fetch_versions(drug: dict, set_id: str) -> dict:
    d = paths.LABELS / slug(drug["ingredient"]) / set_id
    d.mkdir(parents=True, exist_ok=True)
    hist = labels.dailymed_history(set_id)
    versions = []
    for h in sorted(hist, key=lambda h: int(h["spl_version"])):
        v = int(h["spl_version"])
        xml_p, json_p = d / f"v{v:04d}.xml.gz", d / f"v{v:04d}.json"
        row = {"version": v, "published_date": h.get("published_date")}
        if not xml_p.exists():
            xml = labels.dailymed_spl_xml(set_id, v, use_cache=False)
            if xml is None:
                row["error"] = "download failed"
                versions.append(row)
                continue
            xml_p.write_bytes(gzip.compress(xml))
        if not json_p.exists():
            doc = parse_spl(gzip.decompress(xml_p.read_bytes()))
            json_p.write_text(json.dumps(doc.to_dict(), ensure_ascii=False))
        doc = json.loads(json_p.read_text())
        row.update(effective_time=doc["effective_time"], n_sections=len(doc["sections"]),
                   n_sentences=sum(len(s["sentences"]) for s in doc["sections"]))
        versions.append(row)
    return {"set_id": set_id, "n_versions": len(versions), "versions": versions}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resolve-only", action="store_true")
    ap.add_argument("--only", nargs="*", help="ingredients to process")
    args = ap.parse_args(argv)
    cfg = json.loads(DRUGS_CONFIG.read_text())
    drugs = [x for x in cfg["drugs"] if not args.only or x["ingredient"] in args.only]
    if not args.resolve_only and not args.only and cfg.get("status") != "confirmed":
        sys.exit(f"{DRUGS_CONFIG.name} has status {cfg.get('status')!r}; confirm the list first or use --only.")
    summary = []
    for drug in drugs:
        res = resolve(drug)
        row = {"ingredient": drug["ingredient"], "brand": drug.get("brand"), **res}
        if not args.resolve_only and res.get("set_id"):
            man = fetch_versions(drug, res["set_id"])
            row["n_versions"] = man["n_versions"]
            first = next((v for v in man["versions"] if "effective_time" in v), None)
            row["oldest_effective_time"] = first and first["effective_time"]
            (paths.LABELS / slug(drug["ingredient"]) / "manifest.json").write_text(
                json.dumps({"drug": drug, "resolved": res, **man}, indent=1))
        summary.append(row)
        print(json.dumps(row), flush=True)
    out = paths.BUILD / "labels" / ("resolve.json" if args.resolve_only else "fetch_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
