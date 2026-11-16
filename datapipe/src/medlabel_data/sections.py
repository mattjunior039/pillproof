"""FDA label sections: LOINC codes, a title-based classifier, and patient relevance.

Codes are the standard LOINC section codes used in Structured Product
Labeling (SPL). FDARxBench often tags subsections with the generic code
42229-5 ("SPL unclassified section"), so `classify_section` looks at the
title first, then the PLR section number (e.g. "8.2" -> specific
populations), then the code.
"""

import re

# code -> (category, display name)
LOINC: dict[str, tuple[str, str]] = {
    "34066-1": ("boxed_warning", "Boxed warning"),
    "34067-9": ("indications", "Indications and usage"),
    "34068-7": ("dosage", "Dosage and administration"),
    "43678-2": ("dosage_forms", "Dosage forms and strengths"),
    "34070-3": ("contraindications", "Contraindications"),
    "43685-7": ("warnings_precautions", "Warnings and precautions"),
    "34071-1": ("warnings", "Warnings"),
    "42232-9": ("precautions", "Precautions"),
    "34072-9": ("precautions", "General precautions"),
    "34084-4": ("adverse_reactions", "Adverse reactions"),
    "90374-0": ("clinical_trials_ae", "Clinical trials experience"),
    "90375-7": ("adverse_reactions", "Postmarketing experience"),
    "34073-7": ("drug_interactions", "Drug interactions"),
    "34074-5": ("drug_interactions", "Drug and laboratory test interactions"),
    "34075-2": ("lab_tests", "Laboratory tests"),
    "43684-0": ("specific_populations", "Use in specific populations"),
    "42228-7": ("specific_populations", "Pregnancy"),
    "34077-8": ("specific_populations", "Teratogenic effects"),
    "34078-6": ("specific_populations", "Nonteratogenic effects"),
    "34079-4": ("specific_populations", "Labor and delivery"),
    "34080-2": ("specific_populations", "Nursing mothers"),
    "77290-5": ("specific_populations", "Lactation"),
    "77291-3": ("specific_populations", "Females and males of reproductive potential"),
    "34081-0": ("specific_populations", "Pediatric use"),
    "34082-8": ("specific_populations", "Geriatric use"),
    "88828-9": ("specific_populations", "Renal impairment"),
    "88829-7": ("specific_populations", "Hepatic impairment"),
    "42227-9": ("abuse_dependence", "Drug abuse and dependence"),
    "34085-1": ("abuse_dependence", "Controlled substance"),
    "34086-9": ("abuse_dependence", "Abuse"),
    "34087-7": ("abuse_dependence", "Dependence"),
    "34088-5": ("overdosage", "Overdosage"),
    "34089-3": ("description", "Description"),
    "34090-1": ("clinical_pharmacology", "Clinical pharmacology"),
    "43679-0": ("clinical_pharmacology", "Mechanism of action"),
    "43681-6": ("clinical_pharmacology", "Pharmacodynamics"),
    "43682-4": ("clinical_pharmacology", "Pharmacokinetics"),
    "66106-6": ("clinical_pharmacology", "Pharmacogenomics"),
    "49489-8": ("clinical_pharmacology", "Microbiology"),
    "43680-8": ("nonclinical_toxicology", "Nonclinical toxicology"),
    "34083-6": ("nonclinical_toxicology", "Carcinogenesis, mutagenesis, impairment of fertility"),
    "34091-9": ("nonclinical_toxicology", "Animal pharmacology and toxicology"),
    "34092-7": ("clinical_studies", "Clinical studies"),
    "34093-5": ("references", "References"),
    "34069-5": ("how_supplied", "How supplied"),
    "44425-7": ("how_supplied", "Storage and handling"),
    "34076-0": ("patient_counseling", "Patient counseling information"),
    "68498-5": ("patient_counseling", "Patient counseling information"),
    "88436-1": ("patient_counseling", "Patient counseling information"),
    "42231-1": ("medication_guide", "Medication guide"),
    "42230-3": ("patient_info", "Patient package insert"),
    "59845-8": ("patient_info", "Instructions for use"),
    "43683-2": ("recent_changes", "Recent major changes"),
    "51945-4": ("package_label", "Package label"),
    "48780-1": ("product_data", "SPL product data elements"),
    "42229-5": ("unclassified", "SPL unclassified section"),
    # OTC "Drug Facts" sections
    "55106-9": ("otc_active_ingredient", "Active ingredient"),
    "55105-1": ("otc_purpose", "Purpose"),
    "50570-1": ("otc_do_not_use", "Do not use"),
    "50569-3": ("otc_ask_doctor", "Ask a doctor before use"),
    "50568-5": ("otc_ask_doctor", "Ask a doctor or pharmacist before use"),
    "50567-7": ("otc_when_using", "When using this product"),
    "50566-9": ("otc_stop_use", "Stop use and ask a doctor"),
    "53414-9": ("otc_pregnancy", "If pregnant or breast-feeding"),
    "50565-1": ("otc_keep_out_of_reach", "Keep out of reach of children"),
    "60561-8": ("otc_other_info", "Other information"),
    "51727-6": ("otc_inactive_ingredients", "Inactive ingredients"),
    "53413-1": ("otc_questions", "Questions"),
    "50741-8": ("otc_safe_handling", "Safe handling warning"),
    "69759-9": ("specific_populations", "Risk summary"),
}

# Sections compared across label versions for label-change alerts (plan section 3, item 15).
SAFETY_CATEGORIES = {
    "boxed_warning", "contraindications", "warnings_precautions", "warnings", "precautions",
    "drug_interactions", "patient_counseling", "medication_guide", "patient_info",
    "otc_do_not_use", "otc_ask_doctor", "otc_when_using", "otc_stop_use", "otc_pregnancy",
}

# Sections an older adult managing their own medicines would plausibly ask about.
PATIENT_CATEGORIES = SAFETY_CATEGORIES | {
    "indications", "dosage", "dosage_forms", "adverse_reactions", "specific_populations",
    "overdosage", "how_supplied", "abuse_dependence",
    "otc_active_ingredient", "otc_purpose", "otc_keep_out_of_reach", "otc_other_info",
    "otc_inactive_ingredients",
}

# PLR top-level section numbers.
_PLR_NUMBER = {
    "1": "indications", "2": "dosage", "3": "dosage_forms", "4": "contraindications",
    "5": "warnings_precautions", "6": "adverse_reactions", "7": "drug_interactions",
    "8": "specific_populations", "9": "abuse_dependence", "10": "overdosage",
    "11": "description", "12": "clinical_pharmacology", "13": "nonclinical_toxicology",
    "14": "clinical_studies", "15": "references", "16": "how_supplied",
    "17": "patient_counseling",
}

# Title keyword rules, checked in order. More specific phrases first.
_TITLE_RULES: list[tuple[str, str]] = [
    (r"clinical (trials?|stud(y|ies)) experience", "clinical_trials_ae"),
    (r"post-?\s?marketing", "adverse_reactions"),
    (r"^(boxed )?warning\s*:|boxed warning", "boxed_warning"),
    (r"indications?\s*(and|&)\s*usage|^uses?$", "indications"),
    (r"dosage forms? and strengths?", "dosage_forms"),
    (r"dosage (and|&) a[a-z]*istration|administration information|^directions|dosing|recommended dos|"
     r"reconstitution", "dosage"),
    (r"ingredients and appearance|product characteristics", "product_data"),
    (r"contraindication", "contraindications"),
    (r"warnings and precautions", "warnings_precautions"),
    (r"^do not use", "otc_do_not_use"),
    (r"^ask a doctor", "otc_ask_doctor"),
    (r"^when using", "otc_when_using"),
    (r"^stop use", "otc_stop_use"),
    (r"pregnant or breast", "otc_pregnancy"),
    (r"keep out of reach", "otc_keep_out_of_reach"),
    (r"^active ingredient", "otc_active_ingredient"),
    (r"^inactive ingredient", "otc_inactive_ingredients"),
    (r"^purposes?$", "otc_purpose"),
    (r"^other information", "otc_other_info"),
    (r"adverse reactions?|side effects", "adverse_reactions"),
    (r"drug interactions?|interactions? with", "drug_interactions"),
    (r"pregnan|lactation|nursing mothers|labor and delivery|reproductive potential|"
     r"pediatric use|geriatric use|renal impairment|hepatic impairment|specific populations|teratogenic",
     "specific_populations"),
    (r"overdos", "overdosage"),
    (r"abuse|dependence|controlled substance", "abuse_dependence"),
    (r"medication guide", "medication_guide"),
    (r"patient counseling|information for patients", "patient_counseling"),
    (r"patient information|patient package insert|instructions for use|consumer information|"
     r"information for the patient", "patient_info"),
    (r"how supplied|storage and handling|^storage", "how_supplied"),
    (r"pharmacokinetic|pharmacodynamic|mechanism of action|clinical pharmacology|microbiology|"
     r"pharmacogenomic|metabolism|absorption|elimination|distribution", "clinical_pharmacology"),
    (r"carcinogenesis|nonclinical|non-clinical|animal (toxicology|pharmacology)", "nonclinical_toxicology"),
    (r"clinical studies|clinical trials", "clinical_studies"),
    (r"^description", "description"),
    (r"^references", "references"),
    (r"principal displa?y panel|principal dispaly panel|package label", "package_label"),
    (r"^warnings?$", "warnings"),
    (r"^precautions|^general precautions", "precautions"),
    (r"laboratory tests", "lab_tests"),
]
_TITLE_RULES_C = [(re.compile(p, re.I), c) for p, c in _TITLE_RULES]
_LEADING_NUM = re.compile(r"^\s*(\d{1,2})(\.\d+)*\.?\s")


def classify_section(title: str | None, code: str | None = None) -> str:
    """Return a section category such as 'contraindications' or 'clinical_pharmacology'."""
    title = " ".join((title or "").split())
    m = _LEADING_NUM.match(title + " ")
    bare = re.sub(r"^[\d.\s]+", "", title).strip()
    for rx, cat in _TITLE_RULES_C:
        if bare and rx.search(bare):
            return cat
    if m and m.group(1) in _PLR_NUMBER:
        cat = _PLR_NUMBER[m.group(1)]
        if cat == "adverse_reactions" and m.group(2) == ".1":
            return "clinical_trials_ae"
        return cat
    if code in LOINC and LOINC[code][0] != "unclassified":
        return LOINC[code][0]
    return "other"


def classify_by_number(title: str | None) -> str | None:
    """Category from a leading PLR section number ('2.5 ...' -> 'dosage'), or None."""
    m = _LEADING_NUM.match(" ".join((title or "").split()) + " ")
    if not m or m.group(1) not in _PLR_NUMBER:
        return None
    cat = _PLR_NUMBER[m.group(1)]
    return "clinical_trials_ae" if cat == "adverse_reactions" and m.group(2) == ".1" else cat


def is_patient_relevant(category: str) -> bool:
    return category in PATIENT_CATEGORIES


def is_safety(category: str) -> bool:
    return category in SAFETY_CATEGORIES
