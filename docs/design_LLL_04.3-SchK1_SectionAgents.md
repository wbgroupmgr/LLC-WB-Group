# design_LLL_04.3 — Schedule K-1 Section Agents: Complete Research & Implementation Spec

**Status:** Research complete. Awaiting implementation.  
**Scope:** `irs/taxAgents/FormSchK1Agent.py` (full rewrite), `irs/Sch_K1.py` (_FILL_MAP_K1 + _buildFillDict fix), `books/2025/Forms/Sch_K1_namespace.json` (logicalKey additions)  
**Date:** 2026-06-11  
**Related:** `design_BUS_04.2_LLCTaxAgent.md`, `PLAN_SchK1_v0.3.md`

---

## 0. Background — Why Three Section Agents?

The K-1 (Form 1065) has three structurally distinct sections. Each requires different data sources and different IRS compliance knowledge:

| Section | fids | K-1 Part | Subject |
|---|---|---|---|
| `AgentSchK1_PartnershipInfo` | f1–f13 | Part I | **Partnership** identity: EIN, name, address, tax year, IRS center |
| `AgentSchK1_PartnerCapital` | f14–f48 | Part II | **Partner** identity, type, ownership %, liabilities, capital account |
| `AgentSchK1_PassiveItems` | f49–f77 | Part III | **Income/deductions**: rental income, interest, §179, SE tax |

The section agents are **expert audit guides** — they run before PDF generation, validate that books data maps correctly to IRS requirements, and give the operator actionable IRS-cited instructions.

---

## 1. Confirmed fid → K-1 Box Mapping (f1–f77)

Derived from `Sch_K1_namespace.json` PDF field paths + 2025 IRS K-1 form structure.  
✓ = already assigned in namespace. All others must be added.

### Part I — Partnership Information (f1–f13)

| fid | fType | PDF shortName | logicalKey | K-1 Line | IRS Label |
|---|---|---|---|---|---|
| f1 | text | f1_1 | `K1_TaxYrBeginMon` | Header | Tax year beginning — month (MM) |
| f2 | text | f1_2 | `K1_TaxYrBeginDay` | Header | Tax year beginning — day (DD) |
| f3 | text | f1_3 | `K1_TaxYrEndMon` | Header | Tax year ending — month (MM) |
| f4 | text | f1_4 | `K1_TaxYrEndDay` | Header | Tax year ending — day (DD) |
| f5 | text | f1_5 | `K1_TaxYr` | Header | Tax year ending — 2-digit year |
| f6 | checkBox | c1_1 | `K1_Final` | Header | Final K-1 |
| f7 | checkBox | c1_2 | `K1_Amended` | Header | Amended K-1 |
| f8 | text | f1_6 | `K1_EIN` ✓ | Line A | Partnership EIN |
| f9 | text | f1_7 | `K1_PshipNm` | Line B | Partnership name |
| f10 | text | f1_8 | `K1_PshipAddr` | Line B | Partnership address (street) |
| f11 | checkBox | c1_3 | `K1_PTP` | Line D | Publicly traded partnership flag |
| f12 | text | f1_9 | `K1_PshipCSZ` | Line B | Partnership city, state, ZIP |
| f13 | text | f1_10 | `K1_IRSCtr` | Line C | IRS Center where return filed |

### Part II — Partner Information (f14–f48)

| fid | fType | PDF shortName | logicalKey | K-1 Line | IRS Label |
|---|---|---|---|---|---|
| f14 | checkBox | c1_4[0] | `K1_PtTypeGP` | Line G | General partner or LLC member-manager |
| f15 | checkText | c1_4[1] | `K1_PtTypeLP` | Line G | Limited partner or other LLC member |
| f16 | checkBox | c1_5[0] | `K1_PtDomestic` | Line H1 | Domestic partner |
| f17 | checkText | c1_5[1] | `K1_PtForeign` | Line H1 | Foreign partner |
| f18 | checkBox | c1_6 | `K1_PtDE` | Line H2 | Disregarded entity (DE) |
| f19 | text | f1_11 | `K1_PtEIN` ✓ | Line E | Partner's SSN or EIN |
| f20 | text | f1_12 | `K1_PtName` | Line F | Partner's name |
| f21 | text | f1_13 | `K1_PtAddr` | Line F | Partner's address / city / state / ZIP |
| f22 | checkBox | c1_7 | `K1_PtRetPlan` | Line I | Partner is a retirement plan (IRA/SEP/Keogh) |
| f23 | text | f1_14 | `K1_J_ProfitBeg` | Box J | Profit % — beginning of year |
| f24 | text | f1_15 | `K1_J_Profit` ✓ | Box J | Profit % — end of year |
| f25 | text | f1_16 | `K1_J_LossBeg` | Box J | Loss % — beginning of year |
| f26 | text | f1_17 | `K1_J_Loss` ✓ | Box J | Loss % — end of year |
| f27 | text | f1_18 | `K1_J_CapBeg` | Box J | Capital % — beginning of year |
| f28 | text | f1_19 | `K1_J_Capital` ✓ | Box J | Capital % — end of year |
| f29 | checkBox | c1_8[0] | `K1_K_GPMethod` | Box K1 | Partner is general partner for §752 recourse rules |
| f30 | checkText | c1_8[1] | `K1_K_LPMethod` | Box K1 | Partner is limited partner for §752 |
| f31 | text | f1_20 | `K1_K_NonrecBeg` | Box K1 | Nonrecourse liabilities — beginning |
| f32 | text | f1_21 | `K1_K_Nonrec` | Box K1 | Nonrecourse liabilities — end |
| f33 | text | f1_22 | `K1_K_QNRBeg` | Box K1 | Qualified nonrecourse financing — beginning |
| f34 | text | f1_23 | `K1_K_QNR` | Box K1 | Qualified nonrecourse financing — end |
| f35 | text | f1_24 | `K1_K_RecBeg` | Box K1 | Recourse liabilities — beginning |
| f36 | text | f1_25 | `K1_K_Rec` | Box K1 | Recourse liabilities — end |
| f37 | checkBox | c1_9 | `K1_K_LowerTier` | Box K1 | K1 includes lower-tier partnership amounts |
| f38 | checkBox | c1_10 | `K1_K2` | Box K2 | K2 applicable checkbox |
| f39 | text | f1_26 | `K1_L1` ✓ | Box L | Beginning capital account |
| f40 | text | f1_27 | `K1_L2` ✓ | Box L | Capital contributed during year |
| f41 | text | f1_28 | `K1_L3` ✓ | Box L | Current year net income (loss) |
| f42 | text | f1_29 | — | Box L | Other increase (decrease) — leave blank unless CPA directs |
| f43 | text | f1_30 | `K1_L4` ✓ | Box L | Withdrawals and distributions |
| f44 | text | f1_31 | `K1_L5` ✓ | Box L | Ending capital account |
| f45 | checkBox | c1_11[0] | `K1_L_TaxBasis` | Box L | Method: Tax basis — **must be checked** |
| f46 | checkText | c1_11[1] | `K1_L_NonTax` | Box L | Method: Non-tax-basis — must be unchecked |
| f47 | text | f1_32 | `K1_N_Beg` | Line N | Net unrecognized §704(c) gain — beginning |
| f48 | text | f1_33 | `K1_N_End` | Line N | Net unrecognized §704(c) gain — end |

### Part III — Income/Deductions (f49–f77)

| fid | fType | logicalKey | K-1 Box | IRS Label | W&B Expected |
|---|---|---|---|---|---|
| f49 | text | `K1_1` ✓ | Box 1 | Ordinary business income (loss) | **$0** — IRC §469(c)(2) |
| f50 | text | `K1_2` ✓ | Box 2 | Net rental real estate income (loss) | IS.net_rental × pct |
| f51 | text | `K1_3` | Box 3 | Other net rental income (loss) | **$0** |
| f52 | text | `K1_4a` | Box 4a | Guaranteed payments — services | **$0** |
| f53 | text | `K1_4b` | Box 4b | Guaranteed payments — capital | **$0** |
| f54 | text | `K1_4c` | Box 4c | Guaranteed payments — total | **$0** |
| f55 | text | `K1_5` ✓ | Box 5 | Interest income | IS.interest_income × pct |
| f56 | text | `K1_6a` | Box 6a | Ordinary dividends | **$0** |
| f57 | text | `K1_6b` | Box 6b | Qualified dividends | **$0** |
| f58 | text | `K1_6c` | Box 6c | Dividend equivalents | **$0** |
| f59 | text | `K1_7` | Box 7 | Royalties | **$0** |
| f60 | text | `K1_8` | Box 8 | Net short-term capital gain (loss) | **$0** (unless asset sold) |
| f61 | text | `K1_9a` | Box 9a | Net long-term capital gain (loss) | **$0** (unless asset sold) |
| f62 | text | `K1_9b` | Box 9b | Collectibles (28%) gain (loss) | **$0** |
| f63 | text | `K1_9c` | Box 9c | Unrecaptured §1250 gain | **$0** (unless asset sold) |
| f64 | text | `K1_10` | Box 10 | Net §1231 gain (loss) | **$0** (unless asset sold) |
| f65 | text | `K1_11_cd` | Box 11 | Other income — code | blank |
| f66 | text | `K1_11` | Box 11 | Other income — amount | **$0** |
| f67 | text | `K1_12_cd` | Box 12 | §179 deduction — code | blank or "A" |
| f68 | text | `K1_12` | Box 12 | §179 deduction — amount | from IS.depreciation if §179 used |
| f69 | text | `K1_12b_cd` | Box 12 | §179 deduction — code line 2 | blank |
| f70 | text | `K1_13_cd` | Box 13 | Other deductions — code | blank |
| f71 | text | `K1_13` | Box 13 | Other deductions — amount | **$0** |
| f72 | text | `K1_13b_cd` | Box 13 | Other deductions — code line 2 | blank |
| f73 | text | `K1_13b` | Box 13 | Other deductions — amount line 2 | **$0** |
| f74 | text | `K1_13c_cd` | Box 13 | Other deductions — code line 3 | blank |
| f75 | text | `K1_13c` | Box 13 | Other deductions — amount line 3 | **$0** |
| f76 | text | `K1_14_cd` | Box 14 | SE earnings — code (always "A") | "A" or blank |
| f77 | text | `K1_14a` ✓ | Box 14a | SE earnings — amount | **$0** — IRC §1402(a)(1) |

---

## 2. Books Data Model (verified from live files)

### 2.1 Owner Record (`llcOwners_WBGroupLLC.json`)

```python
{
    "SSN":     "XXX-XX-XXXX",           # partner SSN (9 digits)
    "addr":    "177 Kingsway Dr, Wimberley, 78676",  # combined string, NO state
    "kw":      ["WT FED#02M03 ..."],    # bank transaction keywords
    "memType": "active",                # general activity status
    "nm":      ["Francis X Rojas"],     # list; use nm[0]
    "oID":     "o20250801_1",
    "pct":     0.96,                    # decimal (96%)
    "status":  "Manager",              # "Manager" or None/absent
    "tID":     null                     # employer ID (if partner is entity)
}
```

**Data gaps in owner record (operator must add or infer):**
- No `city`, `state`, `zip` separately — `addr` is one combined string, missing state
- No `is_foreign` flag (infer False: SSN present = domestic US person)
- No `is_de` flag (infer False: individual humans are never disregarded entities)
- No `contributions` key → need to derive from bank/ledger (llcAssets contributions entries)
- No `distributions` key → derive from bank (owner draw entries)

### 2.2 LLC Profile (`llcProfile_WBGroupLLC.json`)

```python
entity = {
    "ein":            "39-3842347",
    "entity_name":    "W&B Group, LLC",
    "address":        "177 Kingsway Dr",
    "city_state_zip": "Wimberley, Tx 78676",
    "date_business_began": "08/29/2025"
}

F1065 = {
    "date_from":  "Jan. 01",   # needs parsing → month="01", day="01"
    "date_to":    "Dec. 31",   # needs parsing → month="12", day="31"
    "tax_year":   null,         # MISSING — must compute from date_to year or hard-code "25"
    "C_city":     "Wimberley",
    "C_state":    "TX",
    "C_zip":      "78676",
    # MISSING keys (must be added to profile or defaulted):
    # "irs_center":     (where Form 1065 was filed, e.g., "Ogden, UT 84201")
    # "is_final_k1":   False
    # "is_amended_k1": False
    # "is_ptp":        False
}
```

### 2.3 IS taxAggregates keys (from stmtIS)

```python
{
    "net_rental":    667.55,   # KEY: net rental income = rent - rental expenses
    "net_income":    667.55,   # same as net_rental for pure rental LLC
    "interest_income": ...,    # Box 5; may be 0
    # NOTE: 'rent_income' key does NOT exist — _buildFillDict() has a bug (see §4)
}
```

### 2.4 BS Data (for Box K1 liabilities)

The mortgage balance from `stmtBS.nSpaceMap()` or `taxAggregates()`:
- Key: `BS.mortgage` (outstanding mortgage balance at year end)
- Partner's share of liabilities = `BS.mortgage × pct`
- Liability type for W&B: **Qualified Nonrecourse Financing** (typical commercial real estate mortgage; §465(b)(6))
  - No partner personally guarantees the loan
  - Lender's only recourse is the property itself
  - Shared in same ratio as profits (Treas. Reg. §1.752-3(a)(3))

---

## 3. _FILL_MAP_K1 Additions Required (`irs/Sch_K1.py`)

Add all entries below to `_FILL_MAP_K1`. Existing entries (K1_EIN, K1_PtEIN, K1_2, etc.) are unchanged.

```python
# ── Tax year header ───────────────────────────────────────────────────────────
"K1_TaxYrBeginMon": {"source": "F1065", "path": "date_from_month",  "note": "Tax year begin MM"},
"K1_TaxYrBeginDay": {"source": "F1065", "path": "date_from_day",    "note": "Tax year begin DD"},
"K1_TaxYrEndMon":   {"source": "F1065", "path": "date_to_month",    "note": "Tax year end MM"},
"K1_TaxYrEndDay":   {"source": "F1065", "path": "date_to_day",      "note": "Tax year end DD"},
"K1_TaxYr":         {"source": "F1065", "path": "tax_year_2d",      "note": "Tax year 2-digit (e.g. '25')"},
# K1_Final and K1_Amended are checkBox types — handled by ftype branch in _buildFillDict
# They need source/path that resolve to CHECK_SENTINEL when True
"K1_Final":         {"source": "F1065", "path": "is_final_k1",      "note": "Final K-1 flag"},
"K1_Amended":       {"source": "F1065", "path": "is_amended_k1",    "note": "Amended K-1 flag"},

# ── Partnership info (Part I) ─────────────────────────────────────────────────
"K1_PshipNm":   {"source": "entity",  "path": "entity_name",    "note": "Partnership name (Line B)"},
"K1_PshipAddr": {"source": "entity",  "path": "address",        "note": "Partnership street address (Line B)"},
"K1_PshipCSZ":  {"source": "entity",  "path": "city_state_zip", "note": "Partnership city/state/ZIP (Line B)"},
"K1_IRSCtr":    {"source": "F1065",   "path": "irs_center",     "note": "IRS Service Center (Line C)"},
# K1_PTP is checkBox — must be unchecked (private LLC); source returns empty string
"K1_PTP":       {"source": "F1065",   "path": "is_ptp",         "note": "PTP flag — always False for private LLC"},

# ── Partner info (Part II) ────────────────────────────────────────────────────
"K1_PtTypeGP":  {"source": "partner", "path": "is_gp_manager",  "note": "Line G: GP/LLC member-manager checkbox"},
"K1_PtTypeLP":  {"source": "partner", "path": "is_lp_member",   "note": "Line G: LP/LLC member checkbox"},
"K1_PtDomestic":{"source": "partner", "path": "is_domestic",    "note": "Line H1: Domestic partner"},
"K1_PtForeign": {"source": "partner", "path": "is_foreign",     "note": "Line H1: Foreign partner"},
"K1_PtDE":      {"source": "partner", "path": "is_de",          "note": "Line H2: Disregarded entity flag"},
"K1_PtName":    {"source": "partner", "path": "name",           "note": "Line F: Partner full name"},
"K1_PtAddr":    {"source": "partner", "path": "address",        "note": "Line F: Partner address/city/state/ZIP"},
"K1_PtRetPlan": {"source": "partner", "path": "is_ret_plan",    "note": "Line I: Retirement plan flag"},

# ── Box J (ownership percentages) ─────────────────────────────────────────────
# Beginning-of-year: $0 for first year; same pct as end for ongoing
"K1_J_ProfitBeg": {"source": "partner", "path": "pct_str_beg", "note": "Box J Profit % beginning"},
"K1_J_LossBeg":   {"source": "partner", "path": "pct_str_beg", "note": "Box J Loss % beginning"},
"K1_J_CapBeg":    {"source": "partner", "path": "pct_str_beg", "note": "Box J Capital % beginning"},
# End-of-year already assigned: K1_J_Profit, K1_J_Loss, K1_J_Capital

# ── Box K1 (liabilities at year end) ─────────────────────────────────────────
# Source: partner_BS — computed as BS.mortgage × pct (QNR financing)
# Beginning = same as prior-year ending (or $0 for first year)
"K1_K_Nonrec":  {"source": "partner_BS", "path": "nonrecourse",    "note": "Box K1 nonrecourse × pct"},
"K1_K_QNR":     {"source": "partner_BS", "path": "qnr",            "note": "Box K1 QNR financing × pct"},
"K1_K_Rec":     {"source": "partner_BS", "path": "recourse",       "note": "Box K1 recourse liabilities × pct"},
# Beginning columns (K1_K_*Beg) — for first year = $0; for ongoing = prior year ending
# Leave as CPA items in first implementation

# ── Box L method ─────────────────────────────────────────────────────────────
"K1_L_TaxBasis": {"source": "F1065", "path": "cap_tax_basis_flag", "note": "Box L: Tax basis (Rev. Proc. 2020-13) — CHECK_SENTINEL"},

# ── Line N — §704(c) ─────────────────────────────────────────────────────────
"K1_N_Beg": {"source": "partner", "path": "sec704c_beg", "note": "Line N §704(c) beginning — $0 if cash-only contributions"},
"K1_N_End": {"source": "partner", "path": "sec704c_end", "note": "Line N §704(c) end — $0 if cash-only contributions"},

# ── Part III — all-zero boxes for rental LLC ─────────────────────────────────
"K1_3":     {"source": "partner_IS", "path": "other_rental",    "note": "Box 3 other rental — $0"},
"K1_4a":    {"source": "partner_IS", "path": "guaranteed_svcs", "note": "Box 4a guaranteed payments — $0"},
"K1_4b":    {"source": "partner_IS", "path": "guaranteed_cap",  "note": "Box 4b guaranteed payments — $0"},
"K1_4c":    {"source": "partner_IS", "path": "guaranteed_tot",  "note": "Box 4c guaranteed payments — $0"},
"K1_6a":    {"source": "partner_IS", "path": "ord_dividends",   "note": "Box 6a dividends — $0"},
"K1_7":     {"source": "partner_IS", "path": "royalties",       "note": "Box 7 royalties — $0"},
"K1_8":     {"source": "partner_IS", "path": "st_cap_gain",     "note": "Box 8 ST cap gain — $0"},
"K1_9a":    {"source": "partner_IS", "path": "lt_cap_gain",     "note": "Box 9a LT cap gain — $0"},
"K1_10":    {"source": "partner_IS", "path": "sec1231_gain",    "note": "Box 10 §1231 gain — $0"},
"K1_12":    {"source": "partner_IS", "path": "sec179",          "note": "Box 12 §179 — from IS if used"},
"K1_14a":   ...,   # already assigned
"K1_19a":   ...,   # already assigned
```

---

## 4. _buildFillDict() Changes Required (`irs/Sch_K1.py`)

### 4.1 Bug Fix — `rent_income` → `net_rental`

```python
# CURRENT (wrong):
rent = float(is_data.get('rent_income', 0))

# FIX:
rent = float(is_data.get('net_rental', 0))
```

### 4.2 Add Date Field Parsing (for f1–f5)

After `entity, f1065_data = self._loadProfile()`, add:

```python
import re as _re

def _parse_month_day(date_str: str):
    """Parse 'Jan. 01' or '01/01' or '01-01' → (month_str, day_str)."""
    month_map = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
                 'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}
    s = str(date_str or '').strip().lower()
    # Named month: "Jan. 01"
    for abbr, mm in month_map.items():
        if s.startswith(abbr):
            day = _re.search(r'(\d{1,2})$', s)
            return mm, (day.group(1).zfill(2) if day else '01')
    # Numeric: MM/DD or MM-DD
    m = _re.match(r'(\d{1,2})[/\-](\d{1,2})', s)
    if m:
        return m.group(1).zfill(2), m.group(2).zfill(2)
    return '01', '01'

bm, bd = _parse_month_day(f1065_data.get('date_from', ''))
em, ed = _parse_month_day(f1065_data.get('date_to', ''))

# Derive 2-digit year from tax_year or from self.tax_year
ty = str(f1065_data.get('tax_year') or self.tax_year or '')[- 2:] or '25'

f1065_data['date_from_month'] = bm
f1065_data['date_from_day']   = bd
f1065_data['date_to_month']   = em
f1065_data['date_to_day']     = ed
f1065_data['tax_year_2d']     = ty
# Default missing profile flags
f1065_data.setdefault('is_final_k1',       False)
f1065_data.setdefault('is_amended_k1',     False)
f1065_data.setdefault('is_ptp',            False)
f1065_data.setdefault('irs_center',        '')
f1065_data.setdefault('cap_tax_basis_flag', True)  # mandatory Rev. Proc. 2020-13
```

### 4.3 Add Partner-Type Flags to `partner_src`

```python
# Determine partner type from owner record
status = partner_raw.get('status', '') or ''
is_manager = 'manager' in status.lower()

# For W&B LLC: managers = GP/member-manager, non-managers = LP/member
partner_src['is_gp_manager']  = CHECK_SENTINEL if is_manager else ''
partner_src['is_lp_member']   = '' if is_manager else CHECK_SENTINEL
partner_src['is_domestic']    = CHECK_SENTINEL  # default: domestic (SSN present = US person)
partner_src['is_foreign']     = ''
partner_src['is_de']          = ''   # individual humans are never disregarded entities
partner_src['is_ret_plan']    = ''
partner_src['pct_str_beg']    = ''   # first year: beginning % blank (entity just formed)
# §704(c): $0 if only cash contributed (no built-in gain/loss)
partner_src['sec704c_beg']    = ''
partner_src['sec704c_end']    = ''
```

### 4.4 Add `partner_BS` Source for Box K1 Liabilities

```python
# Load BS mortgage for Box K1 partner's share of liabilities
mortgage_total = 0.0
try:
    from ledger.stmtBS import stmtBS_Tax
    bs_agg = stmtBS_Tax(self.llc).taxAggregates()
    mortgage_total = float(bs_agg.get('mortgage', 0))
except Exception:
    pass

partner_mortgage = round(mortgage_total * pct, 2)

partner_bs_src: Dict = {
    "nonrecourse":  "",                              # typically $0 for recourse RE
    "qnr":          self._fmt(partner_mortgage) if partner_mortgage else "",
    "recourse":     "",                              # $0 unless personal guarantee
}
src_map["partner_BS"] = partner_bs_src
```

### 4.5 Extend `partner_is_src` for New Part III Boxes

```python
# Extend partner_is_src with all-zero boxes for rental LLC
# If IS has specific keys (future), these will pick up real values
partner_is_src.update({
    "other_rental":    "",   # Box 3 — $0
    "guaranteed_svcs": "",   # Box 4a — $0
    "guaranteed_cap":  "",   # Box 4b — $0
    "guaranteed_tot":  "",   # Box 4c — $0
    "ord_dividends":   "",   # Box 6a — $0
    "royalties":       "",   # Box 7 — $0
    "st_cap_gain":     "",   # Box 8 — $0
    "lt_cap_gain":     "",   # Box 9a — $0
    "sec1231_gain":    "",   # Box 10 — $0
    "sec179":          self._fmt(round(float(is_data.get('depreciation_sec179', 0)) * pct, 2))
                       if is_data.get('depreciation_sec179') else "",
})
```

### 4.6 Fix checkBox Handling

Current code in Step F sets all checkBox to `checkedValue` unconditionally:
```python
if ftype in ("checkBox", "checkText", "box"):
    value = fd.get("checkedValue", "/1")
```

This is wrong — it checks ALL checkboxes. Fix to only check when the source resolves to a truthy value:

```python
if ftype in ("checkBox", "checkText", "box"):
    # Only publish/check if the source resolves to a truthy value
    resolved = self._resolve(spec["source"], spec["path"], src_map)
    if not resolved:
        continue  # leave as unpublished (unchecked)
    value = fd.get("checkedValue", "/1")
else:
    value = self._resolve(spec["source"], spec["path"], src_map) or ""
```

This requires that boolean flags use `CHECK_SENTINEL` as their value (or any truthy string). Import `CHECK_SENTINEL` from `BookToIRS` if not already imported.

---

## 5. Namespace logicalKey Additions (`books/2025/Forms/Sch_K1_namespace.json`)

Add these `logicalKey` and `label` values (all others in f1–f77 already assigned or intentionally left blank):

```
f1  → K1_TaxYrBeginMon  / "Tax year beginning — month (MM)"
f2  → K1_TaxYrBeginDay  / "Tax year beginning — day (DD)"
f3  → K1_TaxYrEndMon    / "Tax year ending — month (MM)"
f4  → K1_TaxYrEndDay    / "Tax year ending — day (DD)"
f5  → K1_TaxYr          / "Tax year ending — 2-digit year"
f6  → K1_Final          / "Final K-1 flag"
f7  → K1_Amended        / "Amended K-1 flag"
f9  → K1_PshipNm        / "Partnership name (Line B)"
f10 → K1_PshipAddr      / "Partnership street address (Line B)"
f11 → K1_PTP            / "Publicly traded partnership (Line D)"
f12 → K1_PshipCSZ       / "Partnership city/state/ZIP (Line B)"
f13 → K1_IRSCtr         / "IRS Service Center (Line C)"
f14 → K1_PtTypeGP       / "Line G: General partner or LLC member-manager"
f15 → K1_PtTypeLP       / "Line G: Limited partner or other LLC member"
f16 → K1_PtDomestic     / "Line H1: Domestic partner"
f17 → K1_PtForeign      / "Line H1: Foreign partner"
f18 → K1_PtDE           / "Line H2: Disregarded entity"
f20 → K1_PtName         / "Partner's name (Line F)"
f21 → K1_PtAddr         / "Partner's address/city/state/ZIP (Line F)"
f22 → K1_PtRetPlan      / "Line I: Partner is retirement plan"
f23 → K1_J_ProfitBeg    / "Box J: Profit % beginning of year"
f25 → K1_J_LossBeg      / "Box J: Loss % beginning of year"
f27 → K1_J_CapBeg       / "Box J: Capital % beginning of year"
f29 → K1_K_GPMethod     / "Box K1: Partner is GP for §752 recourse rules"
f30 → K1_K_LPMethod     / "Box K1: Partner is LP for §752 rules"
f31 → K1_K_NonrecBeg    / "Box K1: Nonrecourse liabilities — beginning"
f32 → K1_K_Nonrec       / "Box K1: Nonrecourse liabilities — end of year"
f33 → K1_K_QNRBeg       / "Box K1: Qualified nonrecourse financing — beginning"
f34 → K1_K_QNR          / "Box K1: Qualified nonrecourse financing — end of year"
f35 → K1_K_RecBeg       / "Box K1: Recourse liabilities — beginning"
f36 → K1_K_Rec          / "Box K1: Recourse liabilities — end of year"
f37 → K1_K_LowerTier    / "Box K1: Includes lower-tier partnership amounts"
f38 → K1_K2             / "Box K2: applicable"
f45 → K1_L_TaxBasis     / "Box L method: Tax basis (mandatory Rev. Proc. 2020-13)"
f46 → K1_L_NonTax       / "Box L method: Non-tax-basis (must be unchecked)"
f47 → K1_N_Beg          / "Line N: Net §704(c) gain — beginning of year"
f48 → K1_N_End          / "Line N: Net §704(c) gain — end of year"
f51 → K1_3              / "Box 3: Other net rental income (loss)"
f52 → K1_4a             / "Box 4a: Guaranteed payments for services"
f53 → K1_4b             / "Box 4b: Guaranteed payments for capital"
f54 → K1_4c             / "Box 4c: Total guaranteed payments"
f56 → K1_6a             / "Box 6a: Ordinary dividends"
f57 → K1_6b             / "Box 6b: Qualified dividends"
f58 → K1_6c             / "Box 6c: Dividend equivalents"
f59 → K1_7              / "Box 7: Royalties"
f60 → K1_8              / "Box 8: Net short-term capital gain (loss)"
f61 → K1_9a             / "Box 9a: Net long-term capital gain (loss)"
f62 → K1_9b             / "Box 9b: Collectibles (28%) gain (loss)"
f63 → K1_9c             / "Box 9c: Unrecaptured §1250 gain"
f64 → K1_10             / "Box 10: Net §1231 gain (loss)"
f65 → K1_11_cd          / "Box 11: Other income — code"
f66 → K1_11             / "Box 11: Other income — amount"
f67 → K1_12_cd          / "Box 12: §179 deduction — code"
f68 → K1_12             / "Box 12: §179 deduction — amount"
f70 → K1_13_cd          / "Box 13: Other deductions — code (line 1)"
f71 → K1_13             / "Box 13: Other deductions — amount (line 1)"
f72 → K1_13b_cd         / "Box 13: Other deductions — code (line 2)"
f73 → K1_13b            / "Box 13: Other deductions — amount (line 2)"
f76 → K1_14_cd          / "Box 14: SE earnings — code"
```

---

## 6. Section Agent Expert Rules

### 6.1 `AgentSchK1_PartnershipInfo` — Part I: f1–f13

**LABEL**: `"Part I: Partnership Identification"`  
**AGENT_KEY**: `"AgentSchK1_PartnershipInfo"`  
**Data access**: `self.llc.F1065` and `self.llc.entity` (partnership-level, not per-partner)

This agent runs **once per K-1 generation pass** (not per-partner), but is structured as a per-partner agent for uniformity. The partnership info is identical on every partner's K-1 so it can be validated once and the result reused.

#### Rules

**SK1A-R01 — Tax Year Accounting Period (IRC §441, §706)**
- W&B Group is a calendar-year partnership (Jan 1 – Dec 31)
- §706(b)(1)(B): a partnership must conform to the tax year of its majority-interest partners, OR the calendar year (if §706(b)(1)(A) doesn't apply)
- Verify: `F1065.date_from` parses to month="01" day="01" AND `F1065.date_to` parses to month="12" day="31"
- If non-calendar year: flag as WARN with explanation that §706 applies
- If `tax_year` is null in profile: flag as ERROR — operator must set it (it must be "25" for 2025)

**SK1A-R02 — EIN Format (IRC §6109; Treas. Reg. §301.6109-1)**
- EIN must be exactly 9 digits in XX-XXXXXXX format
- Validate: strip dashes → 9 digits, isdigit() → True
- Mismatch or missing EIN = IRS rejection of the entire return (not just this K-1)
- Each partner gets the SAME EIN on their K-1

**SK1A-R03 — Partnership Name Consistency**
- Name on K-1 must match exactly the name on Form 1065 page 1 line 1
- IRS uses computer matching — a name typo or abbreviation may cause matching failure
- Check: `entity.entity_name` is not blank

**SK1A-R04 — IRS Service Center (Form 1065 Instructions p.4)**
- K-1 Line C: where the partnership filed its return
- For 2025: most partnerships file at Ogden, UT 84201 or electronically (write "E-File")
- W&B: if e-filed → "E-File"; if paper filed → "Ogden, UT 84201"
- If `F1065.irs_center` is blank → WARN: "Set irs_center in llcProfile F1065 section"

**SK1A-R05 — PTP Flag Must Be Unchecked (IRC §7704)**
- A publicly traded partnership (PTP) requires interests to be traded on an established market
- W&B Group is a private LLC with 3 individual members — categorically NOT a PTP
- If `is_ptp` is True → ERROR: "W&B Group does not meet §7704(b) PTP criteria"
- Default: False (unchecked)

**SK1A-R06 — Final K-1 (Form 1065 Instructions)**
- Check "Final K-1" if this is the last K-1 issued to this partner (partner leaving or LLC liquidating)
- A Final K-1 triggers the partner to recognize any remaining §704(d) basis and may trigger gain/loss on the liquidation
- If `is_final_k1` is True → INFO: confirm partner disposition event occurred this tax year

**SK1A-R07 — Amended K-1 (Form 1065 Instructions)**
- Check "Amended K-1" if issuing a corrected K-1 after the original was filed
- Amended K-1 must be provided to partner AND filed with IRS
- If `is_amended_k1` is True → INFO: confirm original K-1 was previously filed

---

### 6.2 `AgentSchK1_PartnerCapital` — Part II: f14–f48

**LABEL**: `"Part II: Partner Capital & Liabilities"`  
**AGENT_KEY**: `"AgentSchK1_PartnerCapital"`  
**Per-partner**: Yes — runs once per partner; Box J/K/L values differ per partner

#### Rules

**SK1B-R01 — Partner Type Classification (IRC §761(b); Form 1065 Instructions Line G)**
- W&B Group is a member-managed LLC
  - Members with "Manager" status → Line G: "General partner or LLC member-manager"
  - Members without manager status → Line G: "Limited partner or other LLC member"
- This distinction matters for §1402 SE tax: managers of member-managed LLCs may owe SE tax; passive members do not
- For W&B rental LLC: ALL income is passive rental (§469) → Box 14a = $0 regardless of type
- Check: `owner.status` field drives which checkbox is set (f14 vs f15)
- If `status` is blank → WARN: "Cannot determine partner type. Set status='Manager' or leave blank for passive member in llcOwners."

**SK1B-R02 — Domestic vs. Foreign Partner (IRC §1441, §1446)**
- Domestic partner: US citizen, US resident alien, or US entity → no withholding required
- Foreign partner: non-US person → partnership must withhold 37% of ECTI (§1446(a))
- Infer domestic if partner has a 9-digit SSN (US SSN format)
- If `tID` is set with EIN format and no SSN: could be foreign corporation — flag for review
- W&B current partners: all domestic → f16 checked, f17 unchecked
- If foreign detected → ERROR: "Foreign partner requires §1446 withholding and Form 8804/8805"

**SK1B-R03 — Disregarded Entity (Treas. Reg. §301.7701-3)**
- A disregarded entity (DE) is a single-member LLC that has not elected corporate treatment
- If a partner is itself an SMLLC (not an individual), the K-1 is issued to the LLC but the checkbox at Line H2 (f18) must be checked
- For W&B: all partners are individual humans (SSN present, `nm` is a person name) → DE = False (unchecked)
- How to detect DE: `owner.tID` is set AND `owner.nm` contains "LLC" or "Trust"
- If DE detected → INFO: "Partner appears to be a disregarded entity. K-1 should show the DE (LLC) as the partner with the checkbox checked. The beneficial owner's SSN goes in Line E."

**SK1B-R04 — Ownership Percentage (IRC §704(b), §706)**
- Box J: profit%, loss%, capital% at beginning AND end of year
- All three (profit/loss/capital) should equal the partner's pct (uniform allocation)
- First year: beginning % = blank (entity formed mid-year or at start of year)
- For W&B first year: beginning = blank; end = pct × 100 formatted as "XX.XX%"
- Verify: sum of all partners' pct = 1.000 (100%) → if not, flag ERROR
- IRC §704(b): allocations must have substantial economic effect (SEE) — uniform pct is a safe harbor

**SK1B-R05 — Box K1: Partner's Share of Liabilities (IRC §752; Treas. Reg. §1.752-3)**
- Partnership liabilities affect each partner's outside basis (IRC §705(a)(2))
- Three categories:
  1. **Recourse** (§1.752-2): Any partner bears economic risk of loss. Share = amount each partner would lose if partnership went bankrupt. For W&B: $0 (no personal guarantees on mortgage, assuming standard commercial loan)
  2. **Qualified Nonrecourse Financing** (§465(b)(6)): Real property financing from commercial lender with no personal guarantees; no conversion to recourse; lender can only foreclose. Partners share in same ratio as profits. **This is the correct category for W&B's mortgage.**
  3. **Nonrecourse** (§1.752-3): No partner bears economic risk. Share = partner's share of minimum gain (complex calculation). Typically $0 for simple rental LLC with one property.
- **W&B rule**: Box K1 QNR = `BS.mortgage × pct`. Report in f34 (end of year). f33 (beginning) = $0 for first year.
- If mortgage > 0 but operator has not confirmed mortgage type → WARN: "Confirm mortgage is qualified nonrecourse financing (§465(b)(6)): commercial lender, no personal guarantees, real property collateral only."

**SK1B-R06 — Box L: Tax Basis Capital Account Method (Rev. Proc. 2020-13; TD 9902)**
- IRS mandated tax basis capital accounts for all partnerships starting 2020
- Checkbox f45 (K1_L_TaxBasis) MUST be checked
- Other methods (§704(b) book, GAAP, Other) are no longer accepted
- Tax basis capital account (IRC §705):
  - Beginning = $0 (first year LLC) or prior-year ending
  - + Capital contributed (cash, property at tax basis)
  - + Distributive share of taxable income (Box 2 amount)
  - − Losses and deductions
  - − Distributions
  - = Ending capital
- Verify mathematical consistency: `beginning + contributions + net_income - distributions = ending`
- If books data doesn't reconcile → ERROR with full equation showing expected vs. computed

**SK1B-R07 — Capital Contribution Sources (IRC §705, §722)**
- Partner's contributed capital comes from `owners[i].contributions` in owner record
- WARNING: current owner record does NOT have a `contributions` key — must be derived from ledger
- How to find contributions: look in llcAssets/llcExpRev for transactions with acct type "CapitalContrib" or similar, filtered by partner kw/oID
- If `contributions` is 0 and this is the first year → flag INFO: "Verify capital contributions. If partners contributed cash at formation, record in llcAssets with acct=CapitalContrib tagged to each partner."

**SK1B-R08 — §704(c) Allocated Gain/Loss (IRC §704(c); Treas. Reg. §1.704-3)**
- §704(c) applies when a partner contributes property with a BUILT-IN GAIN or LOSS
  (i.e., property's FMV ≠ tax basis at contribution date)
- For W&B: if partners contributed CASH ONLY → §704(c) = $0 → Line N = blank
- If property was contributed (e.g., a partner contributed the rental house) → §704(c) gain/loss must be tracked and disclosed on Line N
- Check: if `BS.land + BS.building > sum(owners.contributions)` → this suggests property was contributed below FMV or with existing basis → flag for CPA review
- For cash-only contributions (most common for new LLC): Line N (f47, f48) = blank

---

### 6.3 `AgentSchK1_PassiveItems` — Part III: f49–f77

**LABEL**: `"Part III: Passive Income & Deductions"`  
**AGENT_KEY**: `"AgentSchK1_PassiveItems"`  
**Per-partner**: Yes — all dollar amounts are IS.value × pct

#### Rules

**SK1C-R01 — Box 1: Ordinary Business Income MUST Be $0 (IRC §469(c)(2))**
- §469(c)(2): "The term 'rental activity' means any activity where payments are principally for the use of tangible property." ALL rental activity income is passive.
- Box 1 derives from Form 1065 Page 1 Lines 3–22 (ordinary income from business operations)
- For a pure rental LLC: Page 1 Lines 3–22 are ALL $0 → Box 1 = $0
- Box 2 (net rental) is the correct box for rental income
- If IS shows any `ordinary_income` > $0 → ERROR: "Non-zero ordinary income on rental LLC. IRC §469(c)(2) categorically classifies all rental activity as passive. Box 1 must be $0. Review Form 1065 Page 1 pipeline."

**SK1C-R02 — Box 2: Net Rental Real Estate Income (IRC §702(a); Books-First IRC §446/703)**
- Box 2 = `IS.net_rental × partner.pct`
- IS.net_rental is the authoritative books-derived value (IRC §446: compute taxable income from books)
- DO NOT source from Schedule K line 2 directly (Cross-form sourcing violates Books-First rule)
- Formula: `Box 2 = IS.net_rental × pct` (rounded to 2 decimal places)
- Cross-validation: Sum of all partners' Box 2 = Schedule K Line 2 (LLCTaxAgent XF-R03 verifies this)
- If net_rental < 0 (rental loss): partners must apply IRC §469 passive activity rules on their individual returns to determine if loss is deductible. K-1 reports the full allocated loss regardless.
- IRC §704(d): partner can only deduct the loss to extent of their adjusted basis — this is computed on the partner's individual return, not on the K-1

**SK1C-R03 — Box 3: Other Net Rental Income = $0 (IRC §469(c)(2))**
- Box 3 is for non-real-estate rental income (equipment, vehicles, etc.)
- W&B Group rents real property ONLY → Box 3 = $0
- If IS has income categorized as `equipment_rental` or similar → WARN: "Other rental income detected. If this is real estate rental, it belongs in Box 2, not Box 3. Only non-real-estate rental (equipment, vehicles) goes in Box 3."

**SK1C-R04 — Box 4: Guaranteed Payments = $0 (IRC §707(c))**
- Guaranteed payments are amounts paid to a partner for services or capital WITHOUT regard to partnership income
- Treated as ordinary income to recipient (§707(c)(2)) and deduction to partnership (§707(c)(1))
- W&B Operating Agreement: no guaranteed payments are specified
- If `IS.management_fees` or similar > 0 AND paid to a partner → WARN: "Partner payments that are not guaranteed payments should be classified as distributions, not deductions. If these are guaranteed payments, they require §707(c) treatment and go in Box 4a/4b."
- Boxes 4a, 4b, 4c = $0 for W&B

**SK1C-R05 — Box 5: Interest Income (IRC §702(a)(1))**
- Interest income is a **separately stated item** per IRC §702(a)(1) — it retains its character
- Partners report it on their individual Schedule B as interest income
- Box 5 = `IS.interest_income × pct`
- Source: bank account interest earned during the year from books
- If IS.interest_income = 0 → Box 5 is blank (correct for most rental LLCs)
- If bank earned interest → verify it's in IS under an interest income account

**SK1C-R06 — Boxes 6a-10: Investment Income = $0**
- W&B Group holds real property, not stocks or investment securities
- Boxes 6a (dividends), 6b (qualified dividends), 6c (dividend equivalents): $0
- Box 7 (royalties): $0 (rental LLC does not license intellectual property)
- Box 8 (short-term capital gain): $0 unless property sold this tax year
- Box 9a (long-term capital gain): $0 unless property sold this tax year
- Box 9c (unrecaptured §1250 gain): $0 unless property sold (depreciation recapture)
- Box 10 (§1231 gain): $0 unless property sold
- IMPORTANT: If property is sold during the year → these boxes WILL be non-zero. Disposition triggers:
  - §1231 gain/loss calculation (Box 10)
  - §1250 unrecaptured depreciation (Box 9c)
  - Long-term capital gain (Box 9a if held > 1 year)
  - These require Form 4797 (property sales) → separate agent handles disposition

**SK1C-R07 — Box 12: §179 Expensing (IRC §179; §469(j)(1))**
- §179 allows immediate expensing of depreciable personal property (NOT real property)
- ELIGIBLE for rental LLC: appliances, HVAC units, furniture, computers used in business
- NOT ELIGIBLE: buildings, land, land improvements classified as §1250 property (§179(b)(5)(B): §179 deduction for §1250 property placed in service after 1986 is $0)
- PASSIVE ACTIVITY LIMITATION (§469(j)(1)): A partner's §179 deduction from a passive rental LLC is limited to the passive income of the partnership in the current year. Excess is suspended and carried forward. This means even if the LLC passes through §179, each partner may not be able to use it immediately.
- If IS has `depreciation_sec179` > 0 → Box 12 = `IS.depreciation_sec179 × pct`, Code = "A"
- Agent rule: if any §179 is detected → INFO: "Box 12 §179 deduction of $X is reported. Partner should verify they have sufficient passive income to absorb this deduction (IRC §469(j)(1)). Suspended §179 carries forward to future years with passive income from this activity."

**SK1C-R08 — Box 13: Other Deductions = $0 (mostly)**
- Box 13 has many codes (A-Z) for various deductions that pass through to partners
- Most relevant for rental LLC:
  - Code H: Investment interest expense (§163(d)) — if LLC borrowed money to invest, NOT for the rental property mortgage
  - Code P: Qualified production activities deduction — N/A for rental
- For W&B: no Box 13 deductions expected
- If IS has any unusual expense categories → WARN with explanation of which Box 13 code applies

**SK1C-R09 — Box 14a: SE Earnings MUST Be $0 (IRC §1402(a)(1); §1402(a)(13))**
- §1402(a)(1): "net earnings from self-employment" explicitly EXCLUDES rentals from real estate, UNLESS the taxpayer provides substantial personal services. A passive rental LLC never provides substantial personal services (that would convert it to a service business, losing §469 passive status)
- §1402(a)(13): Limited partners are not subject to SE tax on their distributive share
- Box 14a = $0 for ALL rental LLC partners regardless of manager/member status
- Non-zero Box 14a would incorrectly subject partners to 15.3% SE tax on rental income → significant IRS penalty exposure
- If `IS.net_rental > 0` and agent receives instruction to set Box 14a = Box 2 → ERROR: "IRC §1402(a)(1) categorically excludes rental income from SE earnings. Box 14a MUST be $0. Do not map rental income to Box 14a."

**SK1C-R10 — IRC §704(d) Basis Limitation Advisory**
- If Box 2 < 0 (rental loss), partner can only deduct to extent of outside basis
- Outside basis = capital account + share of debt (Box K1 QNR)
- This is computed on the partner's individual return (Form 6198, Schedule E)
- K-1 always reports the FULL allocated amount regardless of basis
- Agent should flag as INFO when Box 2 < 0: "This rental loss is subject to basis limitation under IRC §704(d). Each partner must verify their adjusted outside basis before claiming the loss on their individual return."

---

## 7. Implementation Checklist (for next session)

Execute in this order. No shortcuts.

### Step 1 — Namespace additions
Edit `books/2025/Forms/Sch_K1_namespace.json`:
- Add all logicalKey entries from Section 5 above (f1-f7, f9-f13, f14-f22 minus already-done, f23/25/27, f29-f38, f45-f48, f51-f54, f56-f68, f70-f77)
- Use `Edit` tool for each field; verify with a single Python check at end

### Step 2 — Fix _buildFillDict() + extend _FILL_MAP_K1
Edit `irs/Sch_K1.py`:
1. Fix `rent_income` → `net_rental` bug (Step D)
2. Add date field parsing (Step E, after `_loadProfile()`)
3. Add partner-type flags to `partner_src`
4. Add `partner_bs_src` for Box K1
5. Extend `partner_is_src` with zero-value Part III entries
6. Fix checkBox handling (Step F)
7. Add all new `_FILL_MAP_K1` entries from Section 3 above

### Step 3 — Rewrite FormSchK1Agent.py
Replace three section agents:
- Remove old: `AgentSchK1_Identity`, `AgentSchK1_PassiveItems`, `AgentSchK1_Capital`
- Add new: `AgentSchK1_PartnershipInfo`, `AgentSchK1_PartnerCapital`, `AgentSchK1_PassiveItems`
- Update `FormSchK1Agent._SECTION_ORDER` to use new classes
- Each agent: implement `pass2_audit()` with all rules from Section 6
- Each agent: implement `pass5_summarize()` with computed values

### Step 4 — Run tests
```bash
python -m tests.test_stmtBS
python -m tests.test_stmtGL
python -m tests.test_stmtIS
```

### Step 5 — Test guided review via Flask
Restart server, open FormSchK1 guided review, run for all partners, verify:
- No "not in namespace" warnings
- Box 2 shows correct net rental × pct
- Box L shows correct capital account
- Box 14a = $0
- Partner SSN found (not "TIN missing")

### Step 6 — Commit both repos and push

---

## 8. Known Data Gaps (operator action required before K-1 is complete)

| Gap | Field | How to Fix |
|---|---|---|
| `F1065.tax_year` = null | f5 (K1_TaxYr) | Set `"tax_year": "25"` in llcProfile F1065 section |
| `F1065.irs_center` missing | f13 (K1_IRSCtr) | Set `"irs_center": "E-File"` if e-filed, or `"Ogden, UT 84201"` |
| Owner `addr` has no state | f21 (K1_PtAddr) | addr = "177 Kingsway Dr, Wimberley, TX 78676" (add TX) |
| Owner `contributions` missing | f40 (K1_L2) | Derive from ledger (CapitalContrib transactions tagged to owner oID) |
| Owner `distributions` missing | f43 (K1_L4) | Derive from ledger (OwnerDraw transactions tagged to owner oID) |
| Box K1 mortgage type unconfirmed | f34 (K1_K_QNR) | Confirm: commercial lender, no personal guarantees = QNRF |

---

## 9. IRS Authority References (for agent docstrings)

| Topic | Authority |
|---|---|
| Tax year | IRC §441, §706; Treas. Reg. §1.441-1 |
| EIN requirement | IRC §6109; Treas. Reg. §301.6109-1 |
| PTP definition | IRC §7704(b) |
| Partner type | IRC §761(b); Form 1065 Inst. Line G |
| Foreign partner withholding | IRC §1441, §1446; Form 8804/8805 |
| Disregarded entity | Treas. Reg. §301.7701-3 |
| Allocation substantial economic effect | IRC §704(b); Treas. Reg. §1.704-1(b)(2) |
| Liability sharing | IRC §752; Treas. Reg. §1.752-2, §1.752-3 |
| Qualified nonrecourse financing | IRC §465(b)(6); Treas. Reg. §1.752-3(a)(3) |
| Capital account method | Rev. Proc. 2020-13; TD 9902; IRC §705 |
| §704(c) contributed property | IRC §704(c); Treas. Reg. §1.704-3 |
| Rental = passive | IRC §469(c)(2) |
| Separately stated items | IRC §702(a) |
| Guaranteed payments | IRC §707(c) |
| §179 limitations | IRC §179; §179(b)(5)(B); §469(j)(1) |
| SE tax exclusion | IRC §1402(a)(1); §1402(a)(13) |
| Basis limitation | IRC §704(d); §705(a) |
| Books-First | IRC §446(a); §703(a) |
