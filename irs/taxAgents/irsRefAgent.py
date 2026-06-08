"""
irs/taxAgents/irsRefAgent.py
-----------------------------
IRS Reference Agent — static knowledge base for the BookToIRS pipeline.

Two dicts per form:
  SECTIONS   — ordered list of sections; each section names its fids.
  REFERENCES — ref_id → { cite, reason, fields } explaining WHY each
               bookNS mapping exists (referencing IRS instructions/IRC).

Reference IDs are short and stable: F4562-H, F4562-179, etc.
Multiple fids may share one reference (e.g. all of Line 19h under F4562-19h).
"""

# ── Form 4562 ─────────────────────────────────────────────────────────────────

_F4562_SECTIONS = [
    {
        "id":    "Header",
        "name":  "Header",
        "fids":  ["F002", "F003", "F004"],
        "ref":   "F4562-H",
    },
    {
        "id":    "PartI",
        "name":  "Part I — §179 Deduction",
        "fids":  ["F005", "F021", "F026"],
        "ref":   "F4562-179",
    },
    {
        "id":    "PartIII-19h",
        "name":  "Part III — Line 19h (Residential Rental MACRS)",
        "fids":  ["F069", "F070", "F071", "F072", "F073", "F074"],
        "ref":   "F4562-19h",
    },
    {
        "id":    "PartIV",
        "name":  "Part IV — Summary (Line 22)",
        "fids":  ["F153"],
        "ref":   "F4562-22",
    },
]

_F4562_REFERENCES = {
    "F4562-H": {
        "fields": ["F002", "F003", "F004"],
        "cite":   "Form 4562 Instructions, Top of Form (Lines A–C)",
        "reason": (
            "F002 (Name) and F003 (EIN): copied from Form 1065 — same entity. "
            "F004 (Business activity, f4): code 531110 = 'Lessors of Residential Buildings "
            "and Dwellings' per NAICS. IRS Form 4562 Line A requires the principal business "
            "activity code from the IRS Table of Business Activity Codes (2024 Instructions "
            "for Form 4562, p.1). Code 531110 matches a residential rental LLC whose sole "
            "activity is leasing single-family homes."
        ),
    },
    "F4562-179": {
        "fields": ["F005", "F021", "F026"],
        "cite":   "IRC §179(b)(1); Rev. Proc. 2024-40; Form 4562 Part I Instructions",
        "reason": (
            "F005 (f5, Line 1): $1,220,000 is the 2025 §179 dollar limitation, "
            "inflation-adjusted per IRC §179(b)(1) and Rev. Proc. 2024-40. "
            "This is a statutory constant — it does not come from the books. "
            "F021 (Line 12): $0 §179 deduction because residential rental real property "
            "(the building structure) is explicitly excluded from §179 by IRC §179(d)(1)(B). "
            "F026 (Line 13): $0 carry-over from prior year — no §179 property was elected "
            "in a prior year."
        ),
    },
    "F4562-19h": {
        "fields": ["F069", "F070", "F071", "F072", "F073", "F074"],
        "cite":   "IRC §168(c)(1), §168(d)(2); Form 4562 Part III Section B Instructions",
        "reason": (
            "Line 19h = Residential rental property (27.5-year GDS class). "
            "F069 (b) Date placed in service: from books (earliest InService date in llcAssets). "
            "F070 (c) Basis: depreciable cost from Acct.Fixed.Tangible.InService — NOTE: "
            "land value is included and must be removed before filing (land is not depreciable "
            "per IRC §1016; see CPA note in Form4562._CPA_NOTES). "
            "F071 (d) 27.5 years: GDS recovery period for residential rental per IRC §168(c)(1). "
            "F072 (e) MM: mid-month convention required for real property per IRC §168(d)(2). "
            "F073 (f) S/L: straight-line method required for GDS residential rental per IRC §168(b)(3). "
            "F074 (g) Depreciation deduction: current-year amount from Acct.Exp.Depreciation."
        ),
    },
    "F4562-22": {
        "fields": ["F153"],
        "cite":   "Form 4562 Part IV Instructions; Form 1065 Instructions, Line 16a",
        "reason": (
            "F153 (f153, Line 22): sum of all depreciation from Parts II and III. "
            "For W&B Group in 2025 this equals Part III Line 19h only — there is no "
            "bonus depreciation (Part II, §168(k)) and no listed property (Part V). "
            "Line 22 flows directly to Form 1065, Line 16a ('Depreciation not claimed "
            "on Schedule A or elsewhere on return') per Form 1065 Instructions p.17. "
            "It also flows to Form 8825 Line 14 (depreciation expense on rental property)."
        ),
    },
}

# ── Form 8825 ─────────────────────────────────────────────────────────────────
# Dynamic: columns A-H correspond to properties. Sections and fids vary by
# property count. The diagnostic shows per-property aggregates from taxAggregates().

_F8825_SECTIONS = [
    {
        "id":   "Income",
        "name": "Rental Income",
        "fids": [],          # populated dynamically per property column
        "ref":  "F8825-INC",
    },
    {
        "id":   "Expenses",
        "name": "Rental Expenses",
        "fids": [],
        "ref":  "F8825-EXP",
    },
    {
        "id":   "Totals",
        "name": "Form Totals (Lines 17–20)",
        "fids": [],
        "ref":  "F8825-TOT",
    },
]

_F8825_REFERENCES = {
    "F8825-INC": {
        "fields": [],
        "cite":   "IRC §61; Form 8825 Instructions, Lines 2a–2c",
        "reason": (
            "Rental income reported on Form 8825 Line 2a (gross rents) and 2b (other income). "
            "Source: Acct.Rev.Rent and Acct.Rev.Fees.Other from the books. "
            "Required for each rental property separately; aggregated at form totals level."
        ),
    },
    "F8825-EXP": {
        "fields": [],
        "cite":   "IRC §162, §168, §163; Form 8825 Instructions, Lines 5–16",
        "reason": (
            "Ordinary and necessary rental expenses per IRC §162. "
            "Repairs (Line 11): Acct.Exp.Repair. Utilities (Line 12): Acct.Exp.Util. "
            "Depreciation (Line 14): Acct.Exp.Depreciation — same amount as Form 4562 Line 22. "
            "Other expenses (Line 17): Acct.Exp.Operating + Acct.Exp.Other combined."
        ),
    },
    "F8825-TOT": {
        "fields": [],
        "cite":   "Form 8825 Instructions, Lines 17–20; Form 1065 Schedule K Line 2",
        "reason": (
            "Line 18 = total expenses. Line 19a = net income/loss per property. "
            "Line 20 = total net rental income/loss across all properties. "
            "Flows to Form 1065 Schedule K Line 2 (net rental real estate income/loss)."
        ),
    },
}

# ── Form 1065 ─────────────────────────────────────────────────────────────────

_F1065_SECTIONS = [
    {
        "id":   "Header",
        "name": "Header / Entity Info",
        "fids": [],          # F002–F007 range; exact fids depend on bookNS
        "ref":  "F1065-H",
    },
    {
        "id":   "Income",
        "name": "Income (Lines 1–7)",
        "fids": [],
        "ref":  "F1065-INC",
    },
    {
        "id":   "Deductions",
        "name": "Deductions (Lines 8–21)",
        "fids": [],
        "ref":  "F1065-DED",
    },
    {
        "id":   "SchedK",
        "name": "Schedule K — Partners' Distributive Share",
        "fids": [],
        "ref":  "F1065-K",
    },
]

_F1065_REFERENCES = {
    "F1065-H": {
        "fields": [],
        "cite":   "Form 1065 Instructions, Top of Form",
        "reason": (
            "Entity name, EIN, address, tax year, and accounting method from the LLC profile. "
            "Business activity code 531110 (Lessors of Residential Buildings) per NAICS."
        ),
    },
    "F1065-INC": {
        "fields": [],
        "cite":   "IRC §61; Form 1065 Instructions, Lines 1–7",
        "reason": (
            "Gross income from rental activity flows from Form 8825 Line 20 to "
            "Form 1065 Line 2 (net rental real estate income). "
            "Ordinary income items sourced from Acct.Rev.* accounts in the books."
        ),
    },
    "F1065-DED": {
        "fields": [],
        "cite":   "IRC §162, §163, §164, §168; Form 1065 Instructions, Lines 8–21",
        "reason": (
            "Ordinary deductions sourced from Acct.Exp.* accounts. "
            "Line 16a (depreciation): equals Form 4562 Line 22. "
            "Rental expenses flow through Form 8825 and are netted before reaching Form 1065."
        ),
    },
    "F1065-K": {
        "fields": [],
        "cite":   "IRC §702, §704; Form 1065 Schedule K Instructions",
        "reason": (
            "Each partner's distributive share is allocated per ownership percentages "
            "in llcProfile propOwners. Schedule K Line 2 = rental net income/loss. "
            "Partners report their K-1 amounts on their individual returns."
        ),
    },
}

# ── Schedule K-1 ─────────────────────────────────────────────────────────────

_SCHK1_SECTIONS = [
    {
        "id":   "PartI",
        "name": "Part I — Partnership Information",
        "fids": [],
        "ref":  "K1-PI",
    },
    {
        "id":   "PartII",
        "name": "Part II — Partner Information",
        "fids": [],
        "ref":  "K1-PII",
    },
    {
        "id":   "PartIII",
        "name": "Part III — Partner's Share of Income",
        "fids": [],
        "ref":  "K1-PIII",
    },
]

_SCHK1_REFERENCES = {
    "K1-PI": {
        "fields": [],
        "cite":   "Form 1065 Schedule K-1 Instructions, Part I",
        "reason": (
            "Partnership EIN, name, and address from the LLC profile. "
            "Required on each partner's K-1 for cross-referencing to Form 1065."
        ),
    },
    "K1-PII": {
        "fields": [],
        "cite":   "Form 1065 Schedule K-1 Instructions, Part II",
        "reason": (
            "Partner TIN, name, address, and ownership percentage from llcProfile propOwners. "
            "Profit/loss/capital sharing ratios used for income allocation per IRC §704(b)."
        ),
    },
    "K1-PIII": {
        "fields": [],
        "cite":   "IRC §702; Form 1065 Schedule K-1 Instructions, Part III",
        "reason": (
            "Box 2: net rental real estate income/loss — each partner's share of "
            "Form 8825 net income, allocated by ownership percentage. "
            "Partners report Box 2 on Schedule E of Form 1040."
        ),
    },
}

# ── Public registry ───────────────────────────────────────────────────────────

SECTIONS: dict[str, list[dict]] = {
    "Form4562": _F4562_SECTIONS,
    "Form8825": _F8825_SECTIONS,
    "Form1065": _F1065_SECTIONS,
    "Sch_K1":   _SCHK1_SECTIONS,
}

REFERENCES: dict[str, dict[str, dict]] = {
    "Form4562": _F4562_REFERENCES,
    "Form8825": _F8825_REFERENCES,
    "Form1065": _F1065_REFERENCES,
    "Sch_K1":   _SCHK1_REFERENCES,
}


def get_sections(form_name: str) -> list[dict]:
    return SECTIONS.get(form_name, [])


def get_reference(form_name: str, ref_id: str) -> dict:
    return REFERENCES.get(form_name, {}).get(ref_id, {})


def fid_to_ref(form_name: str, fid: str) -> str | None:
    """Return the ref_id for a given fid, or None if not in any section."""
    for sec in SECTIONS.get(form_name, []):
        if fid in sec["fids"]:
            return sec["ref"]
    return None
