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
# Form 8825 fid layout (2024/2025 IRS PDF, sequential namespace IDs):
#
#  Page 1 (Properties A–D):
#   F001–F022  Property headers: entity name/EIN/address, property type,
#               placed-in-service date, fair-rental days, personal-use days
#               per property column A–D.
#   F023–F034  Income: Line 2a gross rents, 2b other income, 2c total income
#               per column A–D (base F023 col A; +1 per col).
#   F035–F102  Expenses: Lines 5–18 (advertising, auto, cleaning, depr,
#               insurance, legal, mgmt, mortgage int, other int, repairs,
#               taxes, utilities, wages, other, Line 18 subtotal, Line 19a net)
#               per column A–D.
#   F103–F113  Summary: Line 20a total rental income, Line 20b total rental
#               expenses, Line 23 total net rental income/loss.
#
#  Page 2 (Properties E–H, offset +114 from page-1 base):
#   F115–F137  Property headers, cols E–H.
#   F142–F153  Income lines, cols E–H.
#   F154–F221  Expense lines, cols E–H.
#
# Section fid assignments follow the user specification:
#   Property: F001–F022 + F115–F137
#   Income:   F023–F034 + F142–F153
#   Expense:  F035–F102 + F154–F221
#   Summary:  F103–F113

def _frange(lo: int, hi: int) -> list:
    return [f"F{n:03d}" for n in range(lo, hi + 1)]

_F8825_SECTIONS = [
    {
        "id":   "Property",
        "name": "Property Headers (Lines 1a–1c)",
        "fids": _frange(1, 22) + _frange(115, 137),
        "ref":  "F8825-PROP",
    },
    {
        "id":   "Income",
        "name": "Rental Income (Lines 2a–2c)",
        "fids": _frange(23, 34) + _frange(142, 153),
        "ref":  "F8825-INC",
    },
    {
        "id":   "Expenses",
        "name": "Rental Expenses (Lines 5–19a)",
        "fids": _frange(35, 102) + _frange(154, 221),
        "ref":  "F8825-EXP",
    },
    {
        "id":   "Summary",
        "name": "Form Summary (Lines 20a–23)",
        "fids": _frange(103, 113),
        "ref":  "F8825-SUM",
    },
]

_F8825_REFERENCES = {
    "F8825-PROP": {
        "fields": _frange(1, 22) + _frange(115, 137),
        "cite":   "IRC §168(a); Form 8825 Instructions, Line 1 Column Headings",
        "reason": [
            "F001–F003: entity name, EIN, address (from llcProfile) — top of form.",
            "F004–F022 (cols A–D): property type description (e.g. '1-family residential'), "
            "placed-in-service date, fair-rental days, personal-use days per property. "
            "IRC §168(a): placed-in-service date required for MACRS to begin. "
            "IRS Form 8825 Instructions: 'Enter the type of property … and the date placed in service.'",
            "CIP RULE (IRC §168 + §263): property NOT yet placed in service has NO column on Form 8825. "
            "RV_RV1 (Acct.Fixed.Tangible.InConstruction) is excluded — no column, no income, no expenses. "
            "Pre-service costs must be capitalized under IRC §263(a), not reported on Form 8825.",
            "F115–F137 (cols E–H, page 2): same fields for properties 5–8.",
        ],
    },
    "F8825-INC": {
        "fields": _frange(23, 34) + _frange(142, 153),
        "cite":   "IRC §61; Pub 527 §1; Form 8825 Instructions, Lines 2a–2c",
        "reason": [
            "Line 2a (F023 col A, +1 per col): Gross rents received or accrued. "
            "IRC §61: all amounts received as rent are gross income. "
            "Books source: Acct.Rev.Rent.{propNm} — ONLY for placed-in-service properties.",
            "Line 2b (F027 col A, +1 per col): Other rental income (cancellation fees, "
            "services in lieu of rent). Books source: Acct.Rev.Fees.Other. "
            "Pub 527: non-rental income belongs on Schedule K, not Form 8825.",
            "Line 2c (F031 col A, +1 per col): Total income = Line 2a + Line 2b (computed).",
            "CIP properties (RV_RV1) contribute ZERO income — they have no column on Form 8825.",
            "F142–F153 (cols E–H, page 2): same lines for properties 5–8.",
        ],
    },
    "F8825-EXP": {
        "fields": _frange(35, 102) + _frange(154, 221),
        "cite":   "IRC §162, §163, §164, §168; Form 8825 Instructions, Lines 5–19a",
        "reason": [
            "Line 11 Repairs (F067 col A): Acct.Exp.Repair — IRC §162 ordinary/necessary maintenance. "
            "NOT capital improvements (those are capitalized per IRC §263).",
            "Line 12 Utilities (F071 col A): Acct.Exp.Util — IRC §162.",
            "Line 14 Depreciation (F079 col A): IS.depreciation — CRITICAL Books-First (IRC §446+703). "
            "Must NOT come from Form 4562; both forms independently sourced from books. "
            "LLCTaxAgent XF-R01 confirms F4562 Line 22 == F8825 Line 14 == IS.depreciation.",
            "Line 16 Taxes (F083 col A): Acct.Exp.Taxes — IRC §164 real property taxes only.",
            "Line 17 Other (F091 col A): Acct.Exp.Operating + Acct.Exp.Other combined — IRC §162.",
            "Line 18 Expense subtotal (F095 col A): sum Lines 5–17 per column (computed).",
            "Line 19a Net income/loss (F099 col A): Line 2c minus Line 18 per column (computed).",
            "CIP properties (RV_RV1) contribute ZERO expenses to Form 8825. "
            "Pre-service costs (IRC §263) must be capitalized in books, not reported here. "
            "F8EX-R05 flags if CIP expenses remain in Acct.Exp.* accounts.",
            "F154–F221 (cols E–H, page 2): same lines for properties 5–8.",
        ],
    },
    "F8825-SUM": {
        "fields": _frange(103, 113),
        "cite":   "Form 8825 Instructions, Lines 20a–23; Form 1065 Schedule K Line 2; IRC §469(c)(2)",
        "reason": [
            "F103 (Line 20a Total Rental Income): sum of all per-column Line 2c values "
            "(active/InService properties ONLY). Source: sum of per-property income_subtotals "
            "from _build_f8825_filldict(). NOT from IS.total_income (which may include CIP).",
            "F104 (Line 20b Total Rental Expenses): sum of all per-column Line 18 values "
            "(active/InService properties ONLY). Source: sum of per-property exp_subtotals. "
            "MUST NOT include pre-service CIP expenses. If books still have CIP expenses in "
            "Acct.Exp.*, F8EX-R05 fires ERROR. After books fix: F104 = H_805HighMesa expenses only.",
            "F113 (Line 23 Total Net Rental Income/Loss): sum of all per-column Line 19a values. "
            "= Line 20a minus Line 20b = active-property total income minus active-property total expenses. "
            "MUST NOT be net_rental from IS.taxAggregates() if books still include CIP expenses. "
            "Source: sum of per-property net_income from _build_f8825_filldict(). "
            "For W&B Group after books fix: F113 = +$681.61 (net rental INCOME, not loss). "
            "Flows to Form 1065 Schedule K Line 2, then K-1 Box 2 for each partner.",
            "IRC §469(c)(2): rental activity is passive; net rental income/loss is a passive item.",
            "F8NI-R04 audit rule fires ERROR if F104/F113 include CIP expenses.",
        ],
    },
}

# ── Form 1065 ─────────────────────────────────────────────────────────────────
#
# Form 1065 uses logical-key fids (P1_*, B_*, K_*, L_*, M1_*, M2_*) rather
# than numeric F### fids. Sections here document the IRS rules for each page/
# schedule; field-level mapping appears in bookNS_Form1065.json once created.
#
# Key IRS rule for W&B Group (pure rental LLC — IRC §469(c)(2)):
#   Page 1 Lines 1–23:  ALL $0 — rental income is PASSIVE, not ordinary.
#   Schedule K Line 2:  net rental income/loss (Books-First: IS.net_rental).
#   Schedule K Line 14: $0 — rental income not subject to SE tax (IRC §1402(a)).
#   Schedules L/M-1/M-2: NOT required unless gross ≥ $250K AND assets ≥ $1M.

# Section fid assignment derived from Form1065_namespace.json page numbers
# (authoritative PDF layout) intersected with the bookNS_Profile + bookNS_IS
# Form1065 mappings.  Page 1 header → GenInfo; Page 1 body → IncStmt;
# Pages 2–3 → SchedB; Pages 4–5 → SchedK; Page 6 → SchedLM.
_F1065_GENINFO_FIDS = [
    "F001", "F002", "F003", "F004", "F005", "F006", "F007", "F008",
    "F009", "F010", "F011", "F012", "F013", "F014", "F015", "F016",
    "F026", "F_business_code", "F_preparer_date",
]
_F1065_INCSTMT_FIDS = [
    "F033", "F034", "F035", "F036", "F037", "F038", "F039", "F040",
    "F041", "F042", "F043", "F044", "F045", "F046", "F047", "F048",
    "F049", "F050", "F051", "F052", "F053", "F054", "F055", "F072",
    "F074", "F075", "F076", "F077", "F078",
]
_F1065_SCHEDB_FIDS = ["F161", "F162", "F164", "F165"]
_F1065_SCHEDK_FIDS = [
    "F215", "F216", "F218", "F219", "F220", "F221", "F228", "F230",
    "F238", "F242", "F243", "F247", "F248", "F249", "F250", "F276",
    "F277", "F279", "F280", "F281", "F282",
]
_F1065_SCHEDLM_FIDS = [
    "F299", "F301", "F339", "F341", "F347", "F349", "F371", "F373",
    "F375", "F377", "F403", "F405", "F407", "F409", "F410", "F411",
    "F426", "F427", "F428", "F429", "F430", "F439", "F440",
    "F_l_cash_beg", "F_l_cash_end",
]

_F1065_SECTIONS = [
    {
        "id":   "GenInfo",
        "name": "Page 1 — General Information (Items A–K)",
        "fids": _F1065_GENINFO_FIDS,
        "ref":  "F1065-INFO",
    },
    {
        "id":   "IncStmt",
        "name": "Page 1 — Income & Deductions (Lines 1–23)",
        "fids": _F1065_INCSTMT_FIDS,
        "ref":  "F1065-INC",
    },
    {
        "id":   "SchedB",
        "name": "Schedule B — Other Information (Pages 2–3)",
        "fids": _F1065_SCHEDB_FIDS,
        "ref":  "F1065-B",
    },
    {
        "id":   "SchedK",
        "name": "Schedule K — Partners' Distributive Share (Pages 4–5)",
        "fids": _F1065_SCHEDK_FIDS,
        "ref":  "F1065-K",
    },
    {
        "id":   "SchedLM",
        "name": "Schedules L / M-1 / M-2 (Page 6)",
        "fids": _F1065_SCHEDLM_FIDS,
        "ref":  "F1065-LM",
    },
]

_F1065_REFERENCES = {
    "F1065-INFO": {
        "fields": _F1065_GENINFO_FIDS,
        "cite":   "Form 1065 Instructions, Page 1 Items A–K; IRC §6109; IRC §6223; Treas. Reg. §301.6223-1",
        "reason": [
            "EIN (Item D): 9-digit Employer Identification Number required on every return (IRC §6109). "
            "Wrong EIN = return processed under wrong entity = penalties + corrections.",
            "Partnership Representative (Schedule B Section): Required post-2018 BBA audit regime "
            "(IRC §6223; Treas. Reg. §301.6223-1). The PR has sole authority to act for the partnership "
            "in IRS proceedings. Must be named with name, address, phone, TIN.",
            "Accounting Method (Item H): must match how the books are actually kept (IRC §446(a)). "
            "W&B Group books depreciation and capitalizes assets → Accrual method.",
            "Number of K-1s (Item I): must equal number of partners in llcOwners. "
            "IRS uses this count to verify every partner filed their K-1.",
            "Initial/Final return (checkboxes): W&B Group 2025 = initial return year — must check Initial.",
            "§465 At-Risk (Item K): for a cash-invested rental LLC, partners are generally at-risk "
            "for their capital contributions. Bookkeeper must confirm before checking.",
        ],
    },
    "F1065-INC": {
        "fields": _F1065_INCSTMT_FIDS,
        "cite":   "IRC §469(c)(2); Form 1065 Instructions Lines 1–23; Form 1065 Instructions Line 16a",
        "reason": [
            "CRITICAL — All Lines 1–23 must be $0 for a pure rental LLC. "
            "IRC §469(c)(2): rental activity is passive by statute. "
            "Passive rental income NEVER belongs on Form 1065 Page 1 Lines 1–8 (ordinary income). "
            "Incorrect flow: Books → Page 1 Lines 1a/3/7 ← IRS violation.",
            "Correct flow for rental income: Books → Form 8825 (per-property detail) "
            "→ Form 8825 Line 21 (net) → Schedule K Line 2 → K-1 Box 2 (per partner).",
            "Line 16a (Depreciation): Form 1065 Instructions state explicitly: "
            "'Do not include rental real estate activities — report that depreciation on Form 8825 Line 14.' "
            "P1_16a must be $0 for a rental LLC. Rental depreciation path: "
            "IS.depreciation → Form 4562 Part III Line 19i → Form 8825 Line 14.",
            "Line 23 (Ordinary Business Income): must be $0 (Line 8 − Line 22; both $0 for rental LLC). "
            "Rental income/loss flows to Schedule K Line 2, not Line 23.",
            "Books-First (IRC §446 + §703): all values sourced from IS.taxAggregates(). "
            "Never source from another IRS form.",
        ],
    },
    "F1065-B": {
        "fields": _F1065_SCHEDB_FIDS,
        "cite":   "Form 1065 Instructions, Schedule B; IRC §6031; IRC §6221(b); Treas. Reg. §1.6031(a)-1(b)(4)",
        "reason": [
            "Schedule B is a Yes/No compliance disclosure register. IRS uses answers to determine "
            "what additional forms apply and which audit regime governs.",
            "Q4(c) — Most important question: if gross receipts < $250K OR assets < $1M, answer 'Yes' "
            "→ Schedules L, M-1, M-2 are NOT required. Filing empty schedules creates IRS audit noise. "
            "(Treas. Reg. §1.6031(a)-1(b)(4))",
            "Q3a (individual >50% owner): must be answered Yes or No — no default. "
            "Determines §267 related-party rules.",
            "Q4d (distributions): must be Yes if any partner received cash distribution. "
            "Links to K-1 Box 19 and Schedule M-2 capital account analysis.",
            "Q21 (BBA opt-out): IRC §6221(b) election to opt out of centralized audit regime. "
            "Default = IN the BBA regime (IRS audits at partnership level via Partnership Representative).",
            "Partnership Representative must appear here with full name, address, phone, TIN.",
        ],
    },
    "F1065-K": {
        "fields": _F1065_SCHEDK_FIDS,
        "cite":   "IRC §702(a); IRC §704(b); Form 1065 Schedule K Instructions; IRC §1402(a)(1); IRC §1402(a)(13)",
        "reason": [
            "Schedule K collects ALL items that flow to partners via K-1. "
            "It is an allocation register, not a second income statement.",
            "Line 1 (Ordinary Business Income): must be $0. "
            "IRC §469(c)(2): rental income is PASSIVE — it goes to Line 2, never Line 1.",
            "Line 2 (Net Rental Real Estate Income/Loss): the central K line. "
            "IRS: 'Use amounts from Form 8825 Line 21.' "
            "Books-First: K_2 = IS.net_rental (total_income − total_expenses). "
            "Must be NET income, not gross rent (IS.rent_income). "
            "Mapping gross rent to K_2 omits all rental expense deductions from partners' returns.",
            "IRC §704(b): all K items must sum to 100% across all K-1s. "
            "Partner ownership percentages must sum to exactly 1.0 (100%).",
            "Line 14 (Self-Employment Income): must be $0. "
            "IRC §1402(a)(1): rental income excluded from SE earnings by statute. "
            "IRC §1402(a)(13): limited partners not subject to SE tax. "
            "Non-zero K_14 incorrectly triggers 15.3% SE tax on partners.",
        ],
    },
    "F1065-LM": {
        "fields": _F1065_SCHEDLM_FIDS,
        "cite":   "Form 1065 Instructions Schedule B Q4(c), Schedule L, Schedule M-1, Schedule M-2; "
                  "Rev. Proc. 2020-13; TD 9902; IRC §705",
        "reason": [
            "These schedules are ONLY required if BOTH: gross receipts ≥ $250K AND assets ≥ $1M. "
            "Below either threshold → Schedule B Q4(c) = 'Yes' → skip all three schedules entirely.",
            "Schedule L (Balance Sheet per Books): must match the BS exactly (Books-First — IRC §446). "
            "L_14_2 (total assets, end of year) must equal BS.total_assets.",
            "Schedule M-1 (Book-to-Tax Reconciliation): Line 1 = IS.net_income (book basis). "
            "Line 9 = Schedule K Line 1 = $0 for rental LLC. "
            "Explains why book net income ≠ ordinary taxable income (rental is passive, not ordinary).",
            "Schedule M-2 (Partners' Capital Accounts): MUST use TAX BASIS METHOD (mandatory post-2020). "
            "Rev. Proc. 2020-13; TD 9902: previous methods (§704(b) book value, GAAP) no longer accepted. "
            "Tax basis = contributions + taxable income − deductions − distributions (IRC §705).",
        ],
    },
}

# ── Schedule K-1 ─────────────────────────────────────────────────────────────
#
# Schedule K-1 (Form 1065) — one per partner, per tax year.
# Key IRS rules for a rental LLC (IRC §469(c)(2)):
#   Box 1  = $0 (ordinary income — rental is PASSIVE, not ordinary)
#   Box 2  = IS.net_rental × partner.pct (Books-First: IRC §446/703)
#   Box 14 = $0 (SE income — rental excluded per IRC §1402(a)(1))
#   Box L  = tax basis method (Rev. Proc. 2020-13; mandatory post-2020)
# Distributions (Box 19): actual cash distributed during the year per llcOwners.
# IRC §704(d) basis limitation: partners can only deduct loss up to their basis.

# Sch_K1 identity fids are named (F_K1_*) from bookNS_Profile; income-box fids
# (F035 Box 1, F036 Box 2, F041 Box 5) and capital fids (F028 Box 19, F029)
# come from bookNS_IS.  Runtime values are per-partner via _build_k1_filldict().
_SCHK1_IDENTITY_FIDS = [
    "F_K1_PartName", "F_K1_PartEIN", "F_K1_PartAddr", "F_K1_PartCity",
    "F_K1_PartState", "F_K1_PartZip", "F_K1_TaxYearFrom", "F_K1_TaxYearTo",
    "F_K1_TaxYear", "F_K1_IRSCenter",
]
_SCHK1_PASSIVE_FIDS = ["F035", "F036", "F041"]
_SCHK1_CAPITAL_FIDS = ["F028", "F029"]

_SCHK1_SECTIONS = [
    {
        "id":   "Identity",
        "name": "Parts I & II — Partnership and Partner Identity",
        "fids": _SCHK1_IDENTITY_FIDS,
        "ref":  "K1-ID",
    },
    {
        "id":   "PassiveItems",
        "name": "Part III — Passive Income Items (Boxes 1–3, 14)",
        "fids": _SCHK1_PASSIVE_FIDS,
        "ref":  "K1-PASSIVE",
    },
    {
        "id":   "Capital",
        "name": "Part II — Capital Account (Box L) + Box 19 Distributions",
        "fids": _SCHK1_CAPITAL_FIDS,
        "ref":  "K1-CAP",
    },
]

_SCHK1_REFERENCES = {
    "K1-ID": {
        "fields": _SCHK1_IDENTITY_FIDS,
        "cite":   "Form 1065 Schedule K-1 Instructions, Parts I–II; IRC §6109; IRC §704(b)",
        "reason": [
            "Part I — Partnership EIN, name, and address from llcProfile. "
            "Required on each K-1 so partners can cross-reference to Form 1065 (IRC §6031).",
            "Part II — Partner TIN, name, and address from llcProfile propOwners. "
            "Partner TIN is required (IRC §6109). Wrong TIN = IRS cannot match K-1 to partner's return.",
            "Profit/loss/capital sharing percentages: must reflect the LLC operating agreement "
            "and sum to exactly 100% across all partners (IRC §704(b)).",
            "Partner type (General/Limited/LLC member): for a rental LLC with member-managers, "
            "members are typically 'LLC member' — not General Partner. "
            "Designation affects SE tax treatment (IRC §1402(a)(13)).",
            "Item G (Partner is a disregarded entity): check if any partner is a single-member LLC "
            "or trust that is disregarded — affects how the K-1 is reported on the partner's return.",
        ],
    },
    "K1-PASSIVE": {
        "fields": _SCHK1_PASSIVE_FIDS,
        "cite":   "IRC §469(c)(2); IRC §702(a); IRC §1402(a)(1); IRC §1402(a)(13); "
                  "Form 1065 Schedule K-1 Instructions, Part III",
        "reason": [
            "Box 1 (Ordinary Business Income/Loss): MUST be $0 for rental LLC. "
            "IRC §469(c)(2): rental activity is passive by statute — it is NEVER ordinary income. "
            "Filing a non-zero Box 1 misclassifies rental income as ordinary and triggers "
            "incorrect self-employment tax analysis on the partner's return.",
            "Box 2 (Net Rental Real Estate Income/Loss): the ONLY income box for a rental LLC. "
            "IRS Instructions: 'Each partner's share of net rental real estate income or loss.' "
            "Books-First (IRC §446/703): Box 2 = IS.net_rental × partner.pct. "
            "CRITICAL: Box 2 is NET (income minus expenses), not gross rent. "
            "Gross rent (IS.rent_income × pct) ≠ Box 2 — that error omits all expense deductions. "
            "Partners report Box 2 on Schedule E, Part II as passive income/loss.",
            "IRC §704(d) Basis Limitation: if Box 2 is a loss, the partner can only deduct "
            "up to their adjusted basis in the partnership. "
            "Basis check is performed on the partner's individual return (Schedule E, Form 6198). "
            "The K-1 reports the full allocated amount regardless of the partner's basis.",
            "Box 14 (Self-Employment Income): MUST be $0 for rental LLC. "
            "IRC §1402(a)(1): rental income from real estate is explicitly excluded from "
            "'net earnings from self-employment' (unless taxpayer renders substantial personal services). "
            "IRC §1402(a)(13): limited partners' distributive share is excluded from SE earnings. "
            "A non-zero Box 14 incorrectly triggers 15.3% SE tax (~$X,XXX) on the partner's return.",
            "Box 3 (Other Net Rental Income): blank for W&B Group — only rental real estate "
            "(Box 2) and no personal property rentals.",
        ],
    },
    "K1-CAP": {
        "fields": _SCHK1_CAPITAL_FIDS,
        "cite":   "IRC §705; Rev. Proc. 2020-13; TD 9902; Form 1065 Schedule K-1 Instructions, Item L",
        "reason": [
            "Box L MUST use the TAX BASIS METHOD of capital reporting (mandatory for tax years 2020+). "
            "Rev. Proc. 2020-13 and TD 9902 eliminated §704(b) book value, GAAP, and 'Other' methods. "
            "Filing with a non-tax-basis method is an IRS compliance failure.",
            "Tax basis capital account formula (IRC §705): "
            "BOY Capital + Contributions + Allocated Income − Allocated Losses − Distributions = EOY Capital.",
            "For W&B Group 2025 (first year of operation): "
            "BOY Capital = $0 (new entity, no prior years). "
            "Contributions = each partner's actual cash contributed (from llcOwners.contributions). "
            "Allocated Income/Loss = Box 2 per partner (net rental × ownership %). "
            "Distributions = actual cash distributed (from llcOwners.distributions). "
            "EOY Capital = contributions + Box 2 − distributions.",
            "Box L method checkbox: 'Tax basis' must be checked. "
            "This checkbox is explicitly validated by IRS automated systems.",
            "IRS uses Box L to verify partners track their basis for IRC §704(d) loss limitations "
            "and to detect §704(c) remedial allocation situations on transfers at above/below book value.",
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
