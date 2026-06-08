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

Field ID Naming Convention
--------------------------
  bookNS JSON uses lowercase sequential fIDs from the namespace: f2, f69, f129 etc.
  This file documents the same fields as F002, F069, F129 (uppercase, for readability).
  Both refer to the same AcroForm field — the sequential ID matches our namespace.json.

  f1_N (IRS shortName in the PDF) vs our sequential fN:
    The IRS PDF XFA uses shortNames like f1_2, f1_68, f2_1.
    Our namespace assigns sequential IDs: f1_2 → our f2, f1_68 → our f69, f2_1 → our f129.
    There is a natural +1 relationship between IRS shortName suffix and our fID ONLY for
    page-1 fields (f1_N → our f(N+1) because f1_1 = our f1 is a pre-header year field).
    Page-2 fields (f2_N) require adding the total count of page-1 fields as offset.

Form 4562 Part Structure (IRS)
-------------------------------
  Part I   (Lines 1–13):    §179 expensing — NOT available for residential rental
  Part II  (Lines 14–16):   Special/bonus depreciation — NOT for 27.5yr property
  Part III (Lines 17–21):   MACRS depreciation
    Section A: general depreciation elections
    Section B: GDS (Lines 19a–19i, including Line 19h residential rental)
    Section C: ADS (Lines 20a–20e)
  Part IV  (Line 22):       Summary — TOTAL depreciation → Form 1065 Line 16a
  Part V   (Lines 23–36):   Listed property (§280F vehicles) — BLANK for W&B Group
  Part VI  (Lines 42–43):   Amortization — BLANK unless startup/org costs exist

Part III Line 19 taxonomy (authoritative):
  19a–19g: Personal/mixed-use MACRS classes (3yr, 5yr, 7yr, 10yr, 12yr, 15yr, 20yr, 25yr)
  19h:     Residential rental property — 27.5yr, MM convention, S/L method (IRC §168(c)(1))
  19i:     Nonresidential real property — 39yr GDS or 40yr ADS (IRC §168(c)(1))
  Line 19i is emphatically NOT for residential rental — using it would misclassify the
  property and apply the wrong recovery period (39yr instead of 27.5yr), violating IRC §168.
"""

# ── Form 4562 ─────────────────────────────────────────────────────────────────

_F4562_SECTIONS = [
    {
        "id":    "Header",
        "name":  "Header",
        # 2025 Form 4562 (published Jan 2026): f1_1=Name, f1_2=EIN, f1_3=BizCode.
        # f1_1 IS the first user-fillable field — it is NOT a pre-header system field.
        # Verified against the actual PDF: seq 1=f1_1, seq 2=f1_2, seq 3=f1_3.
        # F001=f1 (Name), F002=f2 (EIN), F003=f3 (Business activity).
        "fids":  ["F001", "F002", "F003"],
        "ref":   "F4562-H",
    },
    {
        "id":    "PartI",
        "name":  "Part I — §179 Deduction",
        # F004=f4 (f1_4, Line 1 dollar limit), F020=f20 (f1_20, Line 12 deduction),
        # F021=f21 (f1_21, Line 13 carryover).
        # NOTE: The old mapping used F005/F021/F026 which were all off by +1.
        # F026=f26=c1_1 (checkbox) — "Val.0" in a checkbox is silently lost.
        "fids":  ["F004", "F020", "F021"],
        "ref":   "F4562-179",
    },
    {
        "id":    "PartIII-19i",
        "name":  "Part III — Line 19i (Residential Rental MACRS, 2025 form)",
        # 2025 CHANGE: Residential rental moved to Line 19i (was 19h in prior years).
        # Line 19h is now "50-year property". Only cols (b), (c), (g) are filled.
        # Cols (d)/(e)/(f) are readOnly pre-printed "27.5 yrs / MM / S/L" by IRS.
        # F075=f75 col(b), F076=f76 col(c), F080=f80 col(g).
        "fids":  ["F075", "F076", "F080"],
        "ref":   "F4562-19i",
    },
    {
        "id":    "PartIV",
        "name":  "Part IV — Summary (Line 22)",
        # Page 2 standalone fields before the Part V checkboxes:
        #   f2_1 (F129) = Line 21: Listed property (from Part V line 28) — BLANK for W&B Group
        #   f2_2 (F130) = Line 22: Total depreciation summary — THIS is the one to fill
        # F153 (f2_18, inside Table_Ln26) is Part V Listed Property table — also wrong.
        "fids":  ["F130"],
        "ref":   "F4562-22",
    },
]

_F4562_REFERENCES = {
    "F4562-H": {
        "fields": ["F001", "F002", "F003"],
        "cite":   "Form 4562 Instructions, Top of Form (Lines A–C); IRC §6109",
        "reason": [
            "F001 (f1, shortName f1_1): Name(s) shown on return — same entity as Form 1065. "
            "VERIFIED: 2025 Form 4562 (IRS PDF published Jan 7 2026, /FT=/Tx at pos 1). "
            "f1_1 IS the first user-fillable field, not a pre-header system field.",
            "F002 (f2, shortName f1_2): Identifying number — partnership EIN from llcProfile.",
            "F003 (f3, shortName f1_3): Business or activity to which this form relates. "
            "Code 531110 = Lessors of Residential Buildings and Dwellings (NAICS).",
        ],
    },
    "F4562-179": {
        "fields": ["F004", "F020", "F021"],
        "cite":   "IRC §179(b)(1), §179(d)(1)(B); Rev. Proc. 2024-40; Form 4562 Part I Instructions",
        "reason": [
            "F004 (f4, shortName f1_4): Line 1 — $1,220,000 dollar limitation (2025, Rev. Proc. 2024-40). "
            "Statutory constant — not sourced from books. Informational; entered even when deduction is $0. "
            "NOTE: Old mapping used f5 (f1_5 = Line 2 'Total cost') — that was WRONG.",
            "F020 (f20, shortName f1_20): Line 12 — $0 §179 deduction. "
            "IRC §179(d)(1)(B): residential rental real property is explicitly excluded. "
            "NOTE: Old mapping used f21 (f1_21 = Line 13 'Carryover') — that was WRONG.",
            "F021 (f21, shortName f1_21): Line 13 — $0 carryover. No §179 election in prior years. "
            "NOTE: Old mapping used f26 (c1_1 = Part II checkbox) — value was silently discarded.",
        ],
    },
    "F4562-19i": {
        # 2025 FORM CHANGE: Residential rental moved from Line 19h to Line 19i.
        # Line 19h is now "50-year property" (new class). Line 19i = residential rental (27.5yr).
        # VERIFIED from 2025 Form 4562 IRS XFA accessibility labels:
        #   Line19h speak: "Row: 19h. 50-year property." col (d) pre-printed "50 yrs." readOnly
        #   Line19i_1 speak: "Row: 19i. Residential rental property. Line 1 of 2. Col (d) 27.5 yrs."
        #   Line19j_1 speak: "Row: 19j. Nonresidential real property. Line 1 of 2. Col (d) 39 yrs."
        "fields": ["F075", "F076", "F080"],
        "cite":   "IRC §168(c)(1), §168(d)(2), §168(b)(3)(B); 2025 Form 4562 Part III Section B Line 19i",
        "reason": [
            "2025 Form 4562 LINE CHANGE: Residential rental is now Line 19i (XFA: Line19i_1/Line19i_2). "
            "Line 19h is now a new '50-year property' row — do NOT use it for residential rental. "
            "IRC §168(c)(1) still mandates 27.5yr for residential rental; the IRS just moved it to Line 19i.",
            "F075 (f75, shortName f1_74): Line19i_1 col (b) — month/year placed in service.",
            "F076 (f76, shortName f1_75): Line19i_1 col (c) — depreciable basis (tangible InService net). "
            "Land MUST be excluded — IRC §167; Treas. Reg. §1.167(a)-2.",
            "Cols (d)(e)(f) = f77/f78/f79 are XFA readOnly with pre-printed '27.5 yrs / MM / S/L'. "
            "Do NOT fill them — they will not override the pre-printed IRS values.",
            "F080 (f80, shortName f1_79): Line19i_1 col (g) — depreciation deduction = IS.depreciation "
            "(Books-First, IRC §446). Line 19i_2 (f81-f86) is a second slot for a second property.",
        ],
    },
    "F4562-22": {
        "fields": ["F130"],
        "cite":   "Form 4562 Part IV Instructions; Form 1065 Instructions Line 16a; IRC §446",
        "reason": [
            "Page 2 standalone fields before the Part V checkboxes (c2_1/c2_2): "
            "f2_1 (F129) = Line 21 'Listed property' (from Part V line 28) — BLANK for W&B Group. "
            "f2_2 (F130) = Line 22 total depreciation — THIS is Part IV Summary. "
            "NOTE: F153 (f2_18, inside Table_Ln26) is Part V Listed Property table — also wrong.",
            "Line 22 = Parts II + III depreciation total. For W&B Group equals Line 19i col(g) only "
            "(no bonus depreciation Part II, no listed property Part V).",
            "Flows to Form 1065 Line 16a. Form 8825 Line 14 sourced independently from IS.depreciation.",
        ],
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
        "reason": [
            "Line 2a Gross rents: sourced from Acct.Rev.Rent per property.",
            "Line 2b Other income: sourced from Acct.Rev.Fees.Other.",
            "Each property column (A–H) is filled separately; form totals aggregate all properties.",
        ],
    },
    "F8825-EXP": {
        "fields": [],
        "cite":   "IRC §162, §168, §163; Form 8825 Instructions, Lines 5–16",
        "reason": [
            "Line 11 Repairs: Acct.Exp.Repair — ordinary and necessary repair costs per IRC §162.",
            "Line 12 Utilities: Acct.Exp.Util.",
            "Line 14 Depreciation: Acct.Exp.Depreciation — must equal Form 4562 Line 22.",
            "Line 17 Other: Acct.Exp.Operating + Acct.Exp.Other combined.",
        ],
    },
    "F8825-TOT": {
        "fields": [],
        "cite":   "Form 8825 Instructions, Lines 17–20; Form 1065 Schedule K Line 2",
        "reason": [
            "Line 18: total expenses across all properties.",
            "Line 19a: net income/loss per property (rents minus expenses).",
            "Line 20: total net rental income/loss — flows to Form 1065 Schedule K Line 2.",
        ],
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
        "reason": [
            "Entity name, EIN, and address: from llcProfile.",
            "Tax year and accounting method: from llcProfile F1065 section.",
            "Business activity code 531110 (Lessors of Residential Buildings) per NAICS.",
        ],
    },
    "F1065-INC": {
        "fields": [],
        "cite":   "IRC §61; Form 1065 Instructions, Lines 1–7",
        "reason": [
            "Line 2: net rental real estate income/loss flows from Form 8825 Line 20.",
            "Ordinary income items sourced from Acct.Rev.* accounts in the books.",
        ],
    },
    "F1065-DED": {
        "fields": [],
        "cite":   "IRC §162, §163, §164, §168; Form 1065 Instructions, Lines 8–21",
        "reason": [
            "Ordinary deductions sourced from Acct.Exp.* accounts.",
            "Line 16a Depreciation: must equal Form 4562 Line 22.",
            "Rental expenses flow through Form 8825 and are netted before reaching Form 1065.",
        ],
    },
    "F1065-K": {
        "fields": [],
        "cite":   "IRC §702, §704; Form 1065 Schedule K Instructions",
        "reason": [
            "Each partner's distributive share allocated per ownership % in llcProfile propOwners.",
            "Schedule K Line 2: rental net income/loss (from Form 8825).",
            "Partners report their K-1 amounts on Schedule E of Form 1040.",
        ],
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
        "reason": [
            "Partnership EIN, name, and address from llcProfile.",
            "Required on each K-1 so partners can cross-reference to Form 1065.",
        ],
    },
    "K1-PII": {
        "fields": [],
        "cite":   "Form 1065 Schedule K-1 Instructions, Part II",
        "reason": [
            "Partner TIN, name, and address from llcProfile propOwners.",
            "Profit/loss/capital sharing ratios used for income allocation per IRC §704(b).",
        ],
    },
    "K1-PIII": {
        "fields": [],
        "cite":   "IRC §702; Form 1065 Schedule K-1 Instructions, Part III",
        "reason": [
            "Box 2: net rental real estate income/loss — each partner's share of Form 8825 net income.",
            "Allocated by ownership percentage from llcProfile.",
            "Partners report Box 2 on Schedule E of Form 1040.",
        ],
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
