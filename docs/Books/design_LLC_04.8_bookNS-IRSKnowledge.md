# bookNS — IRS Knowledge Base Design

**Namespace** LLC (app architecture)
**Stage**     04.8 — IRS Tax Preparation pipeline
**Relates to** `docs/BUS/design_BUS_04.8_Tax_BookToIRS.md` (overall BookToIRS pipeline)
**Status**    v1.1 — active (bookNS_integrity + diagState added Jun 2026)

---

## 1. What Is bookNS?

`bookNS` is the **IRS Knowledge Base** for the BookToIRS pipeline. It is the single
authoritative record of how each IRS form field is sourced from the LLC's financial books.

It is NOT:
- Auto-generated (unlike `*_namespace.json`, which is derived from the IRS PDF)
- Runtime state (unlike `*_session_state.json` or `*_diagnose_state.json`)
- Configuration (unlike `~/.llcRentalTracker/config.json`)

It IS:
- Operator-authored IRS + accounting knowledge, accumulated over time
- The **only** place where the question "which IRS field gets which book value?" is answered
- Analogous to a Chart of Accounts: built once per form, maintained at year boundaries,
  corrected when the IRS redesigns a form
- Versioned alongside the LLC's financial data in the **BUS git repo**

```
books/{year}/Forms/
    bookNS_Profile.json    # Profile.* → IRS fid (entity name, EIN, partners)
    bookNS_BS.json         # Balance Sheet accounts → IRS fid
    bookNS_IS.json         # Income Statement accounts → IRS fid
    bookNS_GL.json         # General Ledger direct accounts → IRS fid
    bookNS_integrity.json  # (in LLC repo) SHA256 of each form section at last VERIFY
```

---

## 2. Two-Layer Structure

Each bookNS file contains two logically distinct layers baked into the same JSON:

### Layer 1 — IRS Form Structure (timeless within a form version)

Maps which IRS field slot carries which financial concept. Follows IRS law and form design.

```json
["f80", "Acct.Exp.Depreciation"]
```
Meaning: Form 4562 Part III Line 19i col(g) [fid f80] receives the current-year
depreciation expense from the books. This is dictated by IRC §168 and the 2025 form
layout — it does not change unless the IRS moves that field to a different position.

### Layer 2 — Year-Specific Constants (changes each tax year)

Literal values that vary by Rev. Proc. or LLC structure changes each year.

```json
["f4", "Val.1,220,000"]
```
Meaning: Form 4562 Part I Line 1 [fid f4] is the §179 dollar limit for 2025
($1,220,000 per Rev. Proc. 2024-40). For 2026 this becomes the 2026 amount.

**Maintenance rule:** At the start of each tax year, only `Val.*` literals need
updating. The structural mappings (Layer 1) carry forward unless the IRS changes
the form layout.

---

## 3. Schema

Each bookNS file has this structure:

```json
{
  "_doc": { ... },            // file-level documentation (purpose, format, scope)

  "_irs_knowledge": {         // IRS knowledge per form — see §4 below
    "Form4562": {
      "Header":     { "cite": "...", "reason": [...], "rules": [...] },
      "PartI":      { ... },
      "PartIII-19i": { ... },
      "PartIV":     { ... }
    }
  },

  "Form1065": [               // fid→UAS mapping pairs for Form 1065
    ["F038", "IS.other_income"],
    ["F039", "IS.total_income"],
    ...
  ],
  "Form4562": [               // fid→UAS mapping pairs for Form 4562
    ["f1", "Val.1,220,000"],
    ...
  ],
  "Form8825": [ ... ],
  "Sch_K1":   [ ... ]
}
```

The `_irs_knowledge` section (§4) is the structured IRS knowledge currently split
across `irsRefAgent.py` and the `design_BUS_04.8_IRS_*_Notes.md` docs.

---

## 4. _irs_knowledge Section (Target Architecture)

### 4.1 Why

Currently IRS knowledge is scattered across three locations:
| Location | What it contains | Problem |
|---|---|---|
| `irsRefAgent.py` | IRC citations, field explanations (REFERENCES) | Python source — requires code change to update |
| `Form4562Agent.py` + siblings | Audit rules per section | Python source — requires code change to update |
| `docs/BUS/design_BUS_04.8_IRS_*_Notes.md` | Field mapping tables, IRS notes | Markdown — goes stale, no runtime access |

The target: **all of this lives in bookNS `_irs_knowledge`**. The Python agents load
it from there. Operators update knowledge by editing JSON, not Python.

### 4.2 _irs_knowledge Schema per Section

```json
"_irs_knowledge": {
  "Form4562": {
    "Header": {
      "cite":   "Form 4562 Instructions, Top of Form; IRC §6109",
      "reason": [
        "F001 (f1): Name(s) shown on return — same entity as Form 1065.",
        "F002 (f2): EIN from llcProfile.",
        "F003 (f3): Business activity code 531110 (Lessors of Residential Buildings)."
      ],
      "rules": [
        {
          "rule_id":  "F45H-R01",
          "severity": "ERROR",
          "check":    "name_present",
          "message":  "Entity name (F001) is blank.",
          "action":   "Verify bookNS_Profile.json maps Profile.entity.entity_name → f1"
        }
      ],
      "fields": [
        {"fid": "F001", "line": "Name", "source": "Profile"},
        {"fid": "F002", "line": "EIN",  "source": "Profile"},
        {"fid": "F003", "line": "Business activity code", "source": "Profile"}
      ]
    }
  }
}
```

### 4.3 How Agents Read It

```python
# irsRefAgent.py (target)
def get_reference(form_name, ref_id):
    # 1. Try bookNS _irs_knowledge first (live, operator-editable)
    knowledge = _load_bookns_knowledge(form_name)
    if knowledge and ref_id in knowledge:
        return knowledge[ref_id]
    # 2. Fall back to Python REFERENCES (static baseline)
    return REFERENCES.get(form_name, {}).get(ref_id, {})
```

This means:
- An operator can update an IRC citation by editing bookNS JSON — no Python deploy
- A section agent can have a new audit rule without touching agent source code
- PA picks up the new knowledge on next `git pull` of BUS repo

### 4.4 IRS Knowledge Aid Button (Target UX)

A new button in the Guided Review header: **📖 IRS Knowledge**

Click opens a panel showing — for the current form and current section:
- The IRC citation (why this field exists)
- The field explanation (what the value means)
- The audit rules that check it (GO/NEEDS_FIXING criteria)
- The current UAS mapping (which book value feeds it)

This is the operator's single reference point. No need to read IRC instructions
directly or open a separate design doc. The knowledge travels with the data.

---

## 5. Lifecycle

### 5.1 At Initial Setup (year 0 for a form)

1. IRS publishes a new form (e.g., Form 4562 for 2025)
2. Run `irsForm._buildNSpace()` → generates `Form4562_namespace.json` (auto, gitignored)
3. Identify which fids need values for this LLC
4. Author the bookNS entries (Layer 1 structural + Layer 2 year constants)
5. Write `_irs_knowledge` for each section (cite, reason, rules)
6. Run `regenerate()` → verify FILL.pdf
7. Run Section Agents → confirm GO on all sections
8. Click VERIFY SECTION per section in Guided Review
9. Commit BUS repo — both bookNS JSON and `_diagnose_state.json`

### 5.2 At Each Tax Year Boundary

1. Update `Val.*` literals for new year amounts (§179 limit, etc.)
2. Check IRS for form revision notes (field moves, new lines)
3. If fids changed: update structural entries + LOCATION_RULES in LLC Python source
4. Run full pipeline; re-verify all sections
5. Commit BUS repo

### 5.3 When IRS Redesigns a Form

This is the scenario that caused the PA/local drift in Jun 2026:

1. IRS changes field positions (e.g., 2025 Form 4562 moved residential rental from
   Line 19h → Line 19i)
2. LLC repo changes required: `LOCATION_RULES`, `irsRefAgent.SECTIONS` fid lists,
   `Form4562Agent.py` section agent fid references
3. **BUS repo changes required (same session):** bookNS structural entries corrected
4. Both repos committed together — see Cross-Repo Commit Rule in `CLAUDE.md`
5. `bookNS_integrity.json` updated automatically on next VERIFY SECTION

**Failure mode:** If only the LLC repo is updated (Python), PA pulls the code change
but the BUS bookNS still has the old fids. The pipeline runs but stamps the wrong
PDF fields. Output looks filled but is wrong. Detected by: `check_integrity()` warning
on next `regenerate()`.

### 5.4 When LLC Structure Changes

| Change | What to update in bookNS |
|---|---|
| New property acquired | Add propNm entries to Form8825 sections in bookNS_IS.json |
| Property sold | Remove or zero-out its propNm entries |
| New income account | Add `Acct.Rev.NewAcct` UAS path to relevant form sections |
| New partner | No bookNS change — partner data in llcProfile; Sch_K1 auto-allocates by pct |

---

## 6. Integrity & Regression Protection

Three mechanisms prevent silent bookNS drift:

### bookNS_integrity.json (in LLC repo, `irs/bookNS_integrity.json`)

Records SHA256 of each `Form{N}` section in each bookNS file at the time the
section was last VERIFIED by the bookkeeper. Committed to the LLC repo so any
environment (local, PA, CI) can detect drift immediately.

```json
{
  "Form4562": {
    "bookNS_IS":      "652518d225e96bd7",
    "bookNS_BS":      "84de1371c79d86c4",
    "bookNS_Profile": "07081529681e4097",
    "verified_at":    "2026-06-08T10:30:00",
    "bus_sha":        "069c56e"
  }
}
```

`check_integrity()` in `irs/formDiagState.py` is called on every `regenerate()`.
Mismatch → `INTEGRITY WARNING` in server log. This fires when:
- BUS bookNS was edited but not committed
- PA's BUS repo is behind remote (stale pull)
- IRS fid correction was applied to LLC code but BUS bookNS wasn't updated

### FormXXXX_diagnose_state.json (in BUS repo, `books/{year}/Forms/`)

Written after every `regenerate()`. Stores per-section field values + SHA256 hash.
When a previously VERIFIED section's hash changes on next regenerate → `REGRESSION`.
Regression is displayed as a red banner in Guided Review with both repo SHAs.

### VERIFY SECTION (bookkeeper checkpoint)

In the Guided Review, once Section Agent reports GO, the bookkeeper clicks
VERIFY SECTION. This:
1. Locks the current field values as the verified baseline
2. Records LLC git SHA + BUS git SHA at time of verification
3. Updates `bookNS_integrity.json` with current bookNS hashes

After VERIFY: any future change that alters the section's output is detectable
without human review — the system flags it automatically.

---

## 7. Cross-Repo Relationship

```
LLC repo (llcRentalTracker)         BUS repo (LLC-WBGroup)
─────────────────────────────       ──────────────────────────────
irs/Form4562.py                     books/2025/Forms/bookNS_IS.json
  LOCATION_RULES                      Form4562: [ [f80, Acct...], ... ]
  _buildNSpace()                      _irs_knowledge: { ... }

irs/taxAgents/irsRefAgent.py        books/2025/Forms/Form4562_diagnose_state.json
  SECTIONS (fid lists)                { "PartI": { verify_state: VERIFIED, ... } }
  REFERENCES (fallback)

irs/bookNS_integrity.json     ←──→  bookNS SHA256 hashes
  (records expected hashes)          (actual file contents)
```

**The invariant:** the fid lists in `irsRefAgent.SECTIONS` and the `LOCATION_RULES`
in `Form4562.py` must match the fid keys in `bookNS_*.json`. When they diverge, the
pipeline fills zero fields and `check_integrity()` fires.

**Enforcement:** See Cross-Repo Commit Rule in `CLAUDE.md §1.1 Github Mgmt`.

---

## 8. Migration Plan (Current → Target)

### Phase 1 — Completed (Jun 2026)
- [x] bookNS_integrity.json — SHA256 check on every regenerate()
- [x] FormXXXX_diagnose_state.json — field values + hash per section
- [x] VERIFY SECTION button — bookkeeper human checkpoint
- [x] Regression detection — VERIFIED + changed hash → REGRESSION banner
- [x] Cross-Repo Commit Rule documented in CLAUDE.md
- [x] Form4562 DIAG_SEC_ID bridge (AGENT_KEY → irsRefAgent section id)

### Phase 2 — Next (v1.2)
- [ ] Add `_irs_knowledge` sections to bookNS files (migrate content from irsRefAgent.py)
- [ ] irsRefAgent.py: load from bookNS `_irs_knowledge` first, fall back to Python
- [ ] New Flask route: `GET /api/aid/irs_knowledge?formNm=Form4562&section=PartI`
- [ ] "IRS Knowledge" button in Guided Review header — loads the knowledge panel
- [ ] Retire the `design_BUS_04.8_IRS_*_Notes.md` stale docs — knowledge now in bookNS

### Phase 3 — Future (v1.3)
- [ ] Section agent rules in bookNS `_irs_knowledge.{form}.{section}.rules`
- [ ] Section agents become generic rule engines — load rules from bookNS
- [ ] New form support = add bookNS entries + `_irs_knowledge` — no Python agent required
- [ ] Year boundary maintenance = edit bookNS `Val.*` entries only — one-step update

---

## 9. Annual Maintenance Checklist (Operator)

At the start of each filing year (January):

```
[ ] IRS releases new form PDFs → run irsForm._buildNSpace() for each form
[ ] Check IRS "What's New" for field moves or new lines
[ ] If fids changed: update LLC LOCATION_RULES + irsRefAgent SECTIONS (Python)
    AND bookNS structural entries (BUS) in the same session commit
[ ] Update Val.* literals (§179 limit, bonus depreciation %, etc.)
[ ] Run regenerate() for all 4 forms — check filled counts
[ ] Run Section Agents on all forms — all should be GO
[ ] Click VERIFY SECTION on all GO sections
[ ] git commit BUS repo (bookNS + diagnose_state + integrity)
[ ] git push both repos; PA git pull on BUS repo; reload server
[ ] Confirm PA output matches local
```
