"""Parse an SPL (Structured Product Labeling) XML document into numbered label sections.

Each `<section>` becomes one record with its LOINC code, its title, its own text (child
sections are separate records) and a category. In real SPL files the LOINC code is
reliable for top-level sections, but subsections (e.g. "5.1 Myopathy") usually carry the
generic code 42229-5, so they are classified by title and otherwise inherit their parent's
category. Highlights (`<excerpt>`) are skipped because they repeat the full text.

Text rendering: paragraphs and list items become separate lines (list items get "• "),
table rows become "cell | cell" lines, <br/> becomes a newline. Images are dropped.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

from .sections import LOINC, classify_by_number, classify_section
from .sentences import split_sentences

NS = {"v3": "urn:hl7-org:v3"}
_V3 = "{urn:hl7-org:v3}"
LOINC_SYSTEM = "2.16.840.1.113883.6.1"
_PLR_SUB = re.compile(r"^\s*\d{1,2}\.\d")  # "2.5 ..."; old labels use "1. Hypertension" as list numbers
_BLOCK = {"paragraph", "item", "tr", "caption", "list", "table", "thead", "tbody", "tfoot"}
_SKIP = {"renderMultiMedia", "observationMedia", "footnote"}


@dataclass
class Section:
    index: int
    parent: int | None
    depth: int
    code: str | None
    code_name: str | None
    title: str
    category: str
    text: str
    sentences: list[str] = field(default_factory=list)


@dataclass
class SplDoc:
    set_id: str
    version: int | None
    effective_time: str | None
    document_type: str | None
    title: str
    products: list[dict]
    sections: list[Section]

    def to_dict(self) -> dict:
        return asdict(self)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(s: str) -> str:
    s = s.replace("\u00a0", " ")
    lines = [" ".join(line.split()) for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def _inline(el) -> str:
    """Text of an element including inline children, without tail."""
    parts = [el.text or ""]
    for ch in el:
        name = _local(ch.tag)
        if name == "br":
            parts.append("\n")
        elif name in _SKIP:
            pass
        elif name in _BLOCK:
            parts.append("\n" + _render(ch) + "\n")
        else:
            parts.append(_inline(ch))
        parts.append(ch.tail or "")
    return "".join(parts)


_BULLET_CAPTION = re.compile(r"^[•●▪◦■□○◆\-–—*·o]$")


def _render_list(el) -> str:
    ordered = el.get("listType") == "ordered"
    lines = []
    n = 0
    for it in el:
        if _local(it.tag) != "item":
            continue
        n += 1
        cap = it.find("v3:caption", NS)
        marker = _clean(_inline(cap)) if cap is not None else ""
        if not marker or _BULLET_CAPTION.match(marker):
            marker = f"{n}." if ordered and not marker else "•"
        parts = [it.text or ""]
        for ch in it:
            if ch is cap:
                parts.append(ch.tail or "")
                continue
            name = _local(ch.tag)
            if name == "br":
                parts.append("\n")
            elif name in _SKIP:
                pass
            elif name in _BLOCK:
                parts.append("\n" + _render(ch) + "\n")
            else:
                parts.append(_inline(ch))
            parts.append(ch.tail or "")
        body = _clean("".join(parts))
        if not body:
            continue
        first, *rest = body.split("\n")
        lines.append(f"{marker} {first}")
        lines += ["  " + r for r in rest]
    return "\n".join(lines)


def _render_table(el) -> str:
    rows = []
    for tr in el.iter(_V3 + "tr"):
        cells = [_clean(_inline(c)) for c in tr if _local(c.tag) in ("td", "th")]
        cells = [c for c in cells if c]
        if len(cells) == 1:
            rows.append(cells[0])
        elif cells:
            rows.append(" | ".join(c.replace("\n", " ") for c in cells))
    cap = el.find("v3:caption", NS)
    head = _clean(_inline(cap)) if cap is not None else ""
    return "\n".join(([head] if head else []) + rows)


def _render(el) -> str:
    name = _local(el.tag)
    if name in _SKIP:
        return ""
    if name == "list":
        return _render_list(el)
    if name == "table":
        return _render_table(el)
    return _clean(_inline(el))


def _section_text(text_el) -> str:
    if text_el is None:
        return ""
    blocks = []
    if (text_el.text or "").strip():
        blocks.append(_clean(text_el.text))
    for ch in text_el:
        r = _render(ch)
        if r:
            blocks.append(r)
        if (ch.tail or "").strip():
            blocks.append(_clean(ch.tail))
    return "\n".join(b for b in blocks if b)


def _title_text(el) -> str:
    return " ".join(_inline(el).split()) if el is not None else ""


def _code(el) -> tuple[str | None, str | None]:
    c = el.find("v3:code", NS)
    if c is None or c.get("codeSystem") != LOINC_SYSTEM:
        return None, None
    return c.get("code"), c.get("displayName")


def _category(code: str | None, title: str, parent_cat: str | None) -> str:
    """Top level: LOINC code, else title. Subsections: PLR number (x.y), else the parent's category
    (so 'Drug Interactions' under 12.3 Pharmacokinetics stays clinical_pharmacology)."""
    if parent_cat is None:
        if code in LOINC and LOINC[code][0] != "unclassified":
            return LOINC[code][0]
        return classify_section(title, code)
    by_num = classify_by_number(title) if _PLR_SUB.match(title) else None
    if by_num:
        return by_num
    if parent_cat in ("other", "unclassified"):
        return classify_section(title, code)
    return parent_cat


def _products(root) -> list[dict]:
    out = []
    for mp in root.iterfind(".//v3:subject/v3:manufacturedProduct/v3:manufacturedProduct", NS):
        name = (mp.findtext("v3:name", default="", namespaces=NS) or "").strip()
        form = mp.find("v3:formCode", NS)
        generic = mp.findtext("v3:asEntityWithGeneric/v3:genericMedicine/v3:name", default="", namespaces=NS)
        actives = []
        for ing in mp.iterfind("v3:ingredient", NS):
            if ing.get("classCode") not in ("ACTIM", "ACTIB", "ACTIR"):
                continue
            num = ing.find("v3:quantity/v3:numerator", NS)
            actives.append({
                "name": (ing.findtext("v3:ingredientSubstance/v3:name", default="", namespaces=NS) or "").strip(),
                "strength": f"{num.get('value')} {num.get('unit')}" if num is not None else None,
            })
        out.append({"name": name, "generic": (generic or "").strip(),
                    "form": form.get("displayName") if form is not None else None, "active_ingredients": actives})
    return out


def parse_spl(xml: bytes | str) -> SplDoc:
    root = ET.fromstring(xml)
    sections: list[Section] = []

    def walk(sec_el, parent: int | None, depth: int, parent_cat: str | None) -> None:
        code, code_name = _code(sec_el)
        title = _title_text(sec_el.find("v3:title", NS))
        cat = _category(code, title, parent_cat)
        text = _clean(_section_text(sec_el.find("v3:text", NS)))
        idx = len(sections)
        sections.append(Section(idx, parent, depth, code, code_name, title, cat, text,
                                split_sentences(text) if text else []))
        for comp in sec_el.findall("v3:component", NS):
            child = comp.find("v3:section", NS)
            if child is not None:
                walk(child, idx, depth + 1, cat)

    body = root.find("v3:component/v3:structuredBody", NS)
    if body is not None:
        for comp in body.findall("v3:component", NS):
            sec = comp.find("v3:section", NS)
            if sec is not None:
                walk(sec, None, 0, None)

    doc_code = root.find("v3:code", NS)
    ver = root.find("v3:versionNumber", NS)
    eff = root.find("v3:effectiveTime", NS)
    return SplDoc(
        set_id=(root.find("v3:setId", NS).get("root") or "").lower(),
        version=int(ver.get("value")) if ver is not None and ver.get("value") else None,
        effective_time=eff.get("value") if eff is not None else None,
        document_type=doc_code.get("displayName") if doc_code is not None else None,
        title=_title_text(root.find("v3:title", NS)),
        products=_products(root),
        sections=sections,
    )
