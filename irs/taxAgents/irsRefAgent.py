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
_F1065_SCHEDB_FIDS = [
    # Page 2: Q1 entity type (c2_1[0-5])
    "F079", "F080", "F081", "F082", "F083", "F084",
    # Page 2: Q2a–Q7 Yes/No pairs
    "F086", "F087",   # Q2a: entity owns 50%+
    "F088", "F089",   # Q2b: individual owns 50%+ (W&B: YES→F088)
    "F090", "F091",   # Q3a: partnership owns 20%+ of corp
    "F112", "F113",   # Q3b: partnership owns 50%+ of another partnership
    "F139", "F140",   # Q4: M-3 required?
    "F141", "F142",   # Q4a: >100 partners?
    "F143", "F144",   # Q4b: BBA opt-out (Schedule B-2)?
    "F145", "F146",   # Q4c: not required to file L/M-1/M-2? (W&B: YES→F145)
    "F148", "F149",   # Q4d: distributed money/property?
    "F150", "F151",   # Q5: foreign partnership?
    "F153", "F154",   # Q6: Forms 8858 attached?
    "F157", "F158",   # Q7: decreased foreign partner interest?
    # Page 3: Q8–Q22 Yes/No pairs
    "F161", "F162",   # Q8: PTP?
    "F164", "F165",   # Q9: Form 8918?
    "F166", "F167",   # Q10: IRS audit?
    "F169", "F170",   # Q11: foreign partners?
    "F173", "F174",   # Q12: Form 1042-S?
    "F176", "F177",   # Q13: PFIC elections?
    "F178", "F179",   # Q14: Form 8886?
    "F182", "F183",   # Q15: foreign partner loan?
    "F184", "F185",   # Q16: withholding foreign partnership?
    "F186", "F187",   # Q17: debt-financed acquisitions?
    "F188", "F189",   # Q18: oil/gas?
    "F191", "F192",   # Q19: §721(c)?
    "F193", "F194",   # Q20: foreign branches?
    "F195", "F196",   # Q21: §754 election?
    "F199", "F200",   # Q22: §267A hybrid mismatch?
    # Page 4: Q23–Q28 Yes/No pairs
    "F203", "F204",   # Q23: CFC partner?
    "F205", "F206",   # Q24: interest income on Line 5?
    "F207", "F208",   # Q26: royalties?
    "F209", "F210",   # Q27: foreign partner distributive share?
    "F212", "F213",   # Q28: foreign corp acquisition?
]
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

# Sch K-1 fid ranges mirror sequential namespace (Sch_K1_namespace.json):
#   f1-f11  → F001-F011  Part I   Partnership Identification (EIN/name/addr/PTP)
#   f12-f48 → F012-F048  Part II  Partner Identity (SSN/name/addr), Box J/K/L
#   f49-f77 → F049-F077  Part III Income/Deduction boxes 1-14
#   f98     → F098        Part III Box 19 (distributions)
# NOTE: f12 (f1_9) = Partner SSN (Line E); f13 (f1_10) = Partner Name (Line F).
#   The K-1 PDF has NO separate AcroForm fields for Partnership CSZ or IRS Center.
_SCHK1_PARTNERSHIPINFO_FIDS = [
    "F001", "F002", "F003", "F004", "F005",   # tax year begin/end month+day + 2-digit year
    "F006", "F007",                            # Final/Amended K-1 checkboxes
    "F008",                                    # Partnership EIN
    "F009", "F010", "F011",                   # name / addr / PTP checkbox
]
_SCHK1_PARTNERCAPITAL_FIDS = [
    "F012", "F013",                            # partner SSN (Line E) / partner name (Line F)
    "F014", "F015",                            # Line G partner type GP/LP checkboxes
    "F016", "F017", "F018",                    # H1 Domestic/Foreign / H2 DE checkboxes
    "F019", "F020", "F021", "F022",            # partner addr (Line F) / unknown / unknown / Line I ret plan
    "F023", "F024", "F025", "F026", "F027", "F028",  # Box J profit/loss/cap % beg+end
    "F029", "F030",                            # Box K1 method checkboxes (GP/LP)
    "F031", "F032", "F033", "F034", "F035", "F036",  # Box K1 liabilities beg+end (nonrec/QNR/rec)
    "F037", "F038",                            # Lower tier / K2 checkboxes
    "F039", "F040", "F041", "F042", "F043", "F044",  # Box L capital L1-L5 + other increase
    "F045", "F046",                            # Box L method checkboxes (Tax Basis / NonTax)
    "F047", "F048",                            # Line N §704(c) beg/end
]
_SCHK1_PASSIVEITEMS_FIDS = [
    "F049", "F050", "F051",                   # Box 1 ordinary / Box 2 net rental / Box 3 other rental
    "F052", "F053", "F054",                   # Box 4a/4b/4c guaranteed payments
    "F055", "F056", "F057", "F058",           # Box 5 interest / Box 6a/6b/6c dividends
    "F059", "F060",                            # Box 7 royalties / Box 8 ST cap gain
    "F061", "F062", "F063", "F064",           # Box 9a/9b/9c LT cap gains / Box 10 §1231
    "F065", "F066", "F067", "F068",           # Box 11 code+amt / Box 12 §179 code+amt
    "F069", "F070", "F071", "F072",           # Box 13 code/amount pairs (first set)
    "F073", "F074", "F075",                   # Box 13 additional code/amount fields
    "F076", "F077",                            # Box 14 SE code + amount
    "F078", "F079",                            # Box 14 additional fields
    "F080", "F081", "F082", "F083",           # Box 15 credits code/amount pairs
    "F084",                                    # Box 16 foreign tax credit checkbox
    "F085", "F086", "F087", "F088",           # Box 17 AMT items code/amount
    "F089", "F090",                            # Box 17 continuation
    "F091", "F092", "F093", "F094",           # Box 18 tax-exempt income code/amount
    "F095", "F096",                            # Box 18 continuation
    "F097",                                    # Box 19 header/code field
    "F098",                                    # Box 19a cash distributions
    "F099", "F100",                            # Box 19b/19c property distributions
    "F101", "F102", "F103", "F104",           # Box 20 code/amount pairs
    "F105", "F106", "F107", "F108",           # Box 20 continuation
    "F109", "F110", "F111",                   # Box 20 end fields + foreign-partner checkboxes
]

_SCHK1_SECTIONS = [
    {
        "id":   "PartnershipInfo",
        "name": "Part I — Partnership Identification (f1–f13)",
        "fids": _SCHK1_PARTNERSHIPINFO_FIDS,
        "ref":  "K1-INFO",
    },
    {
        "id":   "PartnerCapital",
        "name": "Part II — Partner Capital & Liabilities (f14–f48)",
        "fids": _SCHK1_PARTNERCAPITAL_FIDS,
        "ref":  "K1-CAP",
    },
    {
        "id":   "PassiveItems",
        "name": "Part III — Partner's Share of Income, Deductions, Credits & Other Items (f49–f111)",
        "fids": _SCHK1_PASSIVEITEMS_FIDS,
        "ref":  "K1-PASSIVE",
    },
]

_SCHK1_REFERENCES = {
    "K1-INFO": {
        "fields": _SCHK1_PARTNERSHIPINFO_FIDS,
        "cite":   "Form 1065 Schedule K-1 Instructions, Parts I–II; IRC §6031; IRC §6109",
        "reason": [
            "Part I — Partnership EIN (F008), name (F009), address (F010) from llcProfile. "
            "Required so partners can cross-reference this K-1 to Form 1065 (IRC §6031).",
            "F010 (f1_8) = Partnership mailing address (street + city/state/zip combined). "
            "The 2024+ K-1 PDF has NO separate AcroForm fields for Line B CSZ or Line C IRS Center "
            "— those visual positions share the address field or are pre-printed. "
            "F012 (f1_9) and F013 (f1_10) are Part II partner identity fields (Lines E/F), "
            "NOT Part I partnership fields. Do not fill F012/F013 from profile data.",
            "Tax year header (F001-F005): begin/end month+day plus 2-digit year. "
            "Must match the Form 1065 tax year exactly.",
            "Final K-1 checkbox (F006): check only in the year the partner exits or LLC dissolves. "
            "Amended K-1 (F007): check if this supersedes a previously filed K-1 for this partner/year.",
            "PTP checkbox (F011): W&B Group LLC is NOT a publicly traded partnership — leave unchecked.",
        ],
    },
    "K1-CAP": {
        "fields": _SCHK1_PARTNERCAPITAL_FIDS,
        "cite":   "IRC §705; Rev. Proc. 2020-13; TD 9902; IRC §704(b); IRC §1402(a)(13); "
                  "Form 1065 Schedule K-1 Instructions, Items H–N",
        "reason": [
            "Partner type (F014/F015): for a rental LLC with member-managers, members are "
            "typically 'LLC member-manager' (GP checkbox F014). Designation affects SE tax treatment "
            "(IRC §1402(a)(13)). Check with CPA — wrong type mis-classifies SE exposure.",
            "Partner SSN/EIN (F012, f1_9, Line E): required by IRC §6109. "
            "The IRS K-1 matching system links this K-1 to the partner's Form 1040 by TIN. "
            "Wrong or missing TIN → IRS CP2000 automated underreporter notices, "
            "unmatched income assessments, and §6721/§6722 information-return penalties "
            "($310 per unfiled/incorrect K-1, 2025 rates). "
            "Action: confirm the SSN in llcOwners matches exactly what the partner "
            "uses on their Form 1040. Format: XXX-XX-XXXX from llcOwners[partner].SSN. "
            "Partner name (F013, f1_10, Line F) and address (F019, f1_11) follow immediately.",
            "Box J ownership percentages (F023-F028): profit/loss/capital %, beginning and end of year. "
            "Must sum to exactly 100% across all partners (IRC §704(b)). "
            "Use figures from the LLC Operating Agreement.",
            "Box K1 liabilities (F031-F036): partner's share of nonrecourse, QNR, and recourse debt "
            "at beginning and end of year. "
            "QNR (Qualified Nonrecourse Financing, F033/F034) = mortgage balance × partner pct — "
            "mortgages on rental real estate are QNR under IRC §465(b)(6). "
            "Partners need correct QNR to establish at-risk basis for loss deductions.",
            "Box L capital reporting method: W&B Group uses the TAX BASIS METHOD (Rev. Proc. 2020-13; "
            "TD 9902). Checkbox F045 ('Tax basis') must be checked; F046 ('Non-tax basis') must be blank. "
            "Tax Basis is mandatory for all U.S. partnerships for tax years 2020 and later. "
            "IRS automated systems validate this checkbox on every K-1.",
            "Tax basis capital account formula (IRC §705): "
            "BOY Capital (F039) + Contributions (F040) + Allocated Income (F041) "
            "− Distributions (F043) = EOY Capital (F044). "
            "For first year of operation: BOY Capital (F039) = $0.",
            "Box L method checkbox (F045): 'Tax basis' must be checked. "
            "This checkbox is explicitly validated by IRS automated systems.",
        ],
    },
    "K1-PASSIVE": {
        "fields": _SCHK1_PASSIVEITEMS_FIDS,
        "cite":   "IRC §469(c)(2); IRC §702(a); IRC §1402(a)(1); IRC §1402(a)(13); "
                  "Form 1065 Schedule K-1 Instructions, Part III",
        "reason": [
            "Box 1 (Ordinary Business Income/Loss, F049): MUST be $0 for rental LLC. "
            "IRC §469(c)(2): rental activity is passive by statute — it is NEVER ordinary income. "
            "Filing a non-zero Box 1 misclassifies rental income as ordinary and triggers "
            "incorrect self-employment tax analysis on the partner's return.",
            "Box 2 (Net Rental Real Estate Income/Loss, F050): the ONLY income box for a rental LLC. "
            "IRS Instructions: 'Each partner's share of net rental real estate income or loss.' "
            "Books-First (IRC §446/703): Box 2 = IS.net_rental × partner.pct. "
            "CRITICAL: Box 2 is NET (income minus expenses), not gross rent. "
            "Partners report Box 2 on Schedule E, Part II as passive income/loss.",
            "IRC §704(d) Basis Limitation: if Box 2 is a loss, the partner can only deduct "
            "up to their adjusted basis in the partnership. "
            "Basis check performed on partner's individual return (Schedule E, Form 6198).",
            "Box 5 (Interest Income, F055): each partner's share = IS.interest_income × partner.pct. "
            "Partners report on Schedule B.",
            "Boxes 6-10 (F056-F064) — dividends, royalties, capital gains: $0 for W&B Group "
            "unless a rental property is sold during the tax year. "
            "Box 8 (F060, ST cap gain) and Box 9a (F061, LT cap gain) arise only on asset sales. "
            "Box 10 (F064, §1231 gain): net gain from depreciable real property held >1 year. "
            "§1250 recapture (Box 9c, unrecaptured depreciation at 25%) applies to sold rental property. "
            "CPA must run Form 4797 for any property disposed of during the year.",
            "Boxes 11-13 (F065-F075) — other income, §179, other deductions: "
            "Box 11 (F065/F066, other income) = $0 for pure rental LLC absent unusual items "
            "(e.g., debt cancellation income under §108). "
            "Box 12 (F067/F068, §179) = $0 — buildings (§1250 property) and land are §179-ineligible. "
            "Box 13 (F069-F075) codes: $0 for W&B Group 2025. No charitable contributions, "
            "investment interest, or portfolio deductions expected. "
            "§163(j) business interest limitation: W&B likely exempt via the small business "
            "exception (§163(j)(3), avg gross receipts ≤ $30M for prior 3 years).",
            "Box 14 (Self-Employment Income, F076/F077): MUST be $0 for ALL rental LLC partners. "
            "IRC §1402(a)(1): rental income from real estate is EXPLICITLY excluded from "
            "'net earnings from self-employment' regardless of the partner's management role. "
            "An active managing member (Francis) is still not subject to SE tax on rental income "
            "because the exclusion is for the NATURE of the income (rental), not for management activity. "
            "A non-zero Box 14 incorrectly triggers 15.3% SE tax on the partner's return.",
            "Boxes 15-18 (F078-F096) — credits, AMT adjustments, tax-exempt income: "
            "$0 for W&B Group 2025. "
            "Box 15 (F080-F083): partnership credits passed through to partners (none for W&B). "
            "Box 16 (F084 checkbox): foreign tax credit — N/A for domestic-only LLC. "
            "Box 17 (F085-F090): AMT preference items (excess §179, accelerated depr) — $0 for W&B. "
            "Box 18 (F091-F096): tax-exempt income/nondeductible expenses — $0 for W&B "
            "(no municipal bonds, no excess meals/entertainment).",
            "Box 19 (F097-F100, Distributions): "
            "Box 19a (F098, cash) = actual cash distributed to each partner (GL-sourced). "
            "NOT multiplied by pct — use actual per-partner distribution amounts from llcOwners. "
            "Box 19b/19c (F099/F100, property distributions) = $0 for W&B Group. "
            "IRC §731: cash distributions ≤ outside basis are not taxable events.",
            "Box 20 (F101-F111) — Code Z and other pass-through items: "
            "Box 20 Code Z (NII, net investment income) = Box 2 amount (IS.net_rental × pct). "
            "IRC §1411: passive rental income IS net investment income subject to 3.8% NIIT. "
            "Partners above NIIT threshold ($200k single / $250k MFJ) report Box 20Z "
            "on Form 8960 Line 4a. This is a separately stated item per IRC §702(a). "
            "W&B should populate Box 20 Code Z = Box 2 amount in the K-1 PDF.",
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
