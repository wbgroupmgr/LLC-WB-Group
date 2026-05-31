# LLC Business Health Agent — Design

**File:** `docs/design_BUS_01.5_BusHealthAgent.md`
**Status:** Design / Pending GitHub Issue
**Target release:** post-v0.7 (v0.8 candidate)

---

## 1. Purpose

The `llcBusHealthAgent` is a diagnostic service that assesses the integrity of the
PA-hosted LLC business environment at a point in time. It answers three questions:

1. **Are the 3 git repos on the host clean and in sync with their remotes?**
2. **Are the account data files (Accts/*.json) valid, git-clean, and consistent with the active eSession?**
3. **Are there any unsaved eSession working-file changes not yet written back to disk?**

It is a read-only, non-destructive agent — it never writes, edits, or commits anything.

---

## 2. Scope

### Host being assessed
PythonAnywhere host (`wbgroup.pythonanywhere.com`) running the `llcRentalTracker` Flask app.

### 3 Git repos on the host

| Alias | Path on PA host | Purpose |
|---|---|---|
| `multiTaskWS` | `~/MultiTaskWS` | Web dispatcher (Werkzeug DispatcherMiddleware) |
| `llcTracker` | `~/pyTracker/llcRentalTracker` | LLC services, Flask app, agents |
| `llcBus` | `bus_repo` from `~/.llcRentalTracker/config.json` | LLC business data files |

### Account files (high-priority checks)
```
<bus_repo>/books/<year>/Accts/*.json
```
`bus_repo` is read from `~/.llcRentalTracker/config.json` (the stanza matching the
active LLC name from `eSession.llc.llcName`). `year` comes from `eSession.llc.year`.

Includes: `llcAssets_<llcName>.json`, `llcExpRev_<llcName>.json`,
`llcPayables_<llcName>.json`, `llcReceivables_<llcName>.json`,
`llcProfile_<llcName>.json`, `ChartOfAccounts_<llcName>.json`

### Other business files (lower-priority checks)
Everything in `~/llc/LLC-WBGroup/` outside `books/<year>/Accts/`:
PDFs, bank statements, notebooks, docs, profile, Claude-Work files.

---

## 3. Invocation

Only the `llcManager` role can invoke the agent.

**Entry point:** Left nav → Admin section → "🔍 Bus Health Check" link
→ GET `/busHealth` → runs agent → renders `llcBusHealth` view

```html
<!-- _nav_dropdown.html addition (under Admin, llcManager guard) -->
<a href="{{ url_for('bus_health') }}"
   class="nav-view-link{% if request.endpoint == 'bus_health' %} nav-active{% endif %}">
   🔍 Bus Health Check</a>
```

---

## 4. Agent Architecture

### 4.1 Module layout

```
util/
  llcBusHealthAgent.py      ← new: health check logic, returns HealthReport
ui/
  llcMgmt.py                ← add: /busHealth route, calls agent, renders view
  templates/
    llcBusHealth.html        ← new: report view template
```

### 4.2 HealthReport data structure

```python
@dataclass
class RepoStatus:
    alias:           str          # "llcBus", "llcTracker", "multiTaskWS"
    path:            str          # absolute path on host
    exists:          bool
    current_branch:  str | None
    uncommitted:     list[str]    # files with local changes (git status --porcelain)
    ahead:           int          # commits ahead of origin/<branch>
    behind:          int          # commits behind origin/<branch>
    fetch_error:     str | None   # network/auth error from git fetch

@dataclass
class FileStatus:
    path:            str          # relative to LLC-WBGroup root
    category:        str          # "acct" | "other"
    git_state:       str          # "clean" | "modified" | "untracked" | "missing"
    json_valid:      bool | None  # None if not a JSON file
    in_esession:     bool | None  # True if eSession holds a working copy of this file
    esession_dirty:  bool | None  # True if eSession working copy differs from disk

@dataclass
class HealthReport:
    timestamp:       str          # ISO 8601
    year:            int          # eSession.llc.year
    llc_name:        str          # eSession.llc.llcName
    bus_repo:        str          # bus_repo from ~/.llcRentalTracker/config.json
    overall:         str          # "ok" | "warning" | "error"
    repos:           list[RepoStatus]
    acct_files:      list[FileStatus]
    other_files:     list[FileStatus]   # only git-dirty ones (to keep noise low)
    env_checks:      dict[str, str]     # key → "ok" | "warning: <msg>"
    errors:          list[str]          # any agent-level exceptions
```

---

## 5. Check Definitions

### 5.1 Environment checks

| Check | Pass condition |
|---|---|
| `multiTaskWS_config` | `~/.MultiTaskWS/MultiTaskWS_config.json` exists and has `WEB_SECRET_KEY` |
| `llcTracker_config` | `~/.llcRentalTracker/config.json` exists and has a valid stanza for active LLC |
| `gpg_passphrase` | `LLC_GPG_PASSPHRASE` in env (set by `llcMgmt.__init__`) |
| `llcBus_path` | `bus_repo` from config (matched by `eSession.llc.llcName`) exists on disk |
| `active_year` | `books/<year>/Accts/` exists under `bus_repo` (`year` from `eSession.llc.year`) |

### 5.2 Git repo checks (per repo)

```bash
git -C <path> fetch --quiet origin          # refresh remote refs
git -C <path> status --porcelain            # uncommitted local changes
git -C <path> rev-list HEAD..origin/<branch> --count   # commits behind
git -C <path> rev-list origin/<branch>..HEAD --count   # commits ahead
```

Severity rules:
- Uncommitted changes in `llcBus` Accts/ → **error** (data at risk)
- Uncommitted changes in `llcBus` other files → **warning**
- Uncommitted changes in `llcTracker` → **warning** (app code drifting)
- Commits behind origin → **warning** (stale)
- Commits ahead origin → **warning** (unpushed work)
- `git fetch` fails (network, auth) → **warning** (can't compare to remote, report local state only)

### 5.3 Account file checks (`books/<year>/Accts/*.json`)

Per file:
1. **Exists on disk** — error if expected file is missing
2. **Valid JSON** — `json.loads()` — error if malformed
3. **Git state** — `git status --porcelain <file>` — warning if modified/untracked
4. **eSession working copy** — check `utilWorkingDB` temp file exists for this DB
5. **eSession dirty** — if temp file exists, compare checksum to disk file; warn if different (unsaved edits in progress)

### 5.4 Other business file checks

Run `git -C <llcBus_path> status --porcelain` once for the whole repo.
Filter out Accts/ files (covered above). Report only files that are modified or untracked.
No JSON validation on non-account files. No eSession check.

---

## 6. Report View — `llcBusHealth.html`

### Layout

```
┌─────────────────────────────────────────────┐
│  🔍 LLC Business Health Check               │
│  Checked: 2026-05-18 14:32:01  ● Overall: ✅ OK │
├─────────────────────────────────────────────┤
│  ENVIRONMENT                          ✅ OK  │
│    MultiTaskWS config .............. ✅      │
│    LLC tracker config .............. ✅      │
│    GPG passphrase .................. ✅      │
│    Business repo path .............. ✅      │
│    Active year (2025) Accts/ ....... ✅      │
├─────────────────────────────────────────────┤
│  GIT REPOS                           ⚠️ 1   │
│    multiTaskWS   main  clean  in sync  ✅   │
│    llcTracker    main  clean  in sync  ✅   │
│    llcBus        main  ⚠️ 2 modified  ⚠️   │
│      M  books/2025/Accts/llcExpRev_WBGroupLLC.json │
│      M  docs/SOP.md                         │
├─────────────────────────────────────────────┤
│  ACCOUNT FILES  books/2025/Accts/    ⚠️ 1   │  ← year from eSession.llc.year
│    llcAssets_WBGroupLLC.json   ✅ clean  ✅ JSON  — no active session │  ← name from eSession.llc.llcName
│    llcExpRev_WBGroupLLC.json   ⚠️ modified  ✅ JSON  ⚠️ session dirty │
│    llcPayables_WBGroupLLC.json ✅ clean  ✅ JSON  — no active session │
│    ...                                       │
├─────────────────────────────────────────────┤
│  OTHER BUSINESS FILES                ✅ OK  │
│    (no uncommitted changes outside Accts/)   │
└─────────────────────────────────────────────┘
```

### Status icons

| Icon | Meaning |
|---|---|
| ✅ | clean / valid / in-sync |
| ⚠️ | warning — action recommended |
| ❌ | error — data integrity at risk |
| — | not applicable |

### Overall rollup logic

```
overall = "ok"
if any repo.uncommitted and file.category == "acct":  overall = "error"
elif any warning condition:                            overall = "warning"
```

---

## 7. Flask Route

```python
@app.route("/busHealth")
@login_required
def bus_health():
    if session.get("role") != "llcManager":
        abort(403)
    from util.llcBusHealthAgent import run_health_check
    report = run_health_check(eSession)
    return render_template("llcBusHealth.html",
                           report=report,
                           obj_type="busHealth")
```

The route is synchronous. All `subprocess` calls to `git` are short-lived
(< 2 seconds each). No background thread needed for the initial implementation.

---

## 8. Implementation Notes

### Resolving bus_repo and llc_name from eSession
```python
llc_name = eSession.llc.llcName          # e.g. "WBGroupLLC"
year     = eSession.llc.year             # e.g. 2025

from ledger.setup_paths import find_stanza
stanza   = find_stanza(llc_name, year)   # reads ~/.llcRentalTracker/config.json
bus_repo = Path(stanza["bus_repo"])      # authoritative path — no hardcoding
```
`find_stanza()` already exists in `ledger/setup_paths.py`. If the stanza is missing,
the agent reports an `env_checks["llcBus_path"] = "error: no config stanza"` and
short-circuits — no git or file checks run.

### git subprocess calls
Use `subprocess.run(["git", "-C", path, ...], capture_output=True, text=True, timeout=10)`.
Never use `shell=True`. Catch `FileNotFoundError` (git not installed) and `subprocess.TimeoutExpired`.

### eSession working-file detection
`utilWorkingDB` writes temp files alongside the live DB. Check for the presence of
`<acct_file>.work` or the registered temp path in `eSession._working`. Compare
`hashlib.md5` of temp vs live file to detect dirty state.

### git fetch and network
`git fetch` requires network access to GitHub. On PA this is available but may be slow.
Wrap in try/except; if fetch fails, set `fetch_error` and skip the behind/ahead counts.
Report local-only state with a "⚠️ remote unreachable — local state only" note.

### Security
The route requires `llcManager` role. The agent reads filesystem and runs read-only git
commands. It does not accept any user-supplied paths — all paths come from the loaded
`eSession` and the hardcoded repo aliases.

---

## 9. Out of Scope (Future)

- Auto-commit or push from the health view (too dangerous in-browser)
- Diff viewer for modified files
- Historical health log (each run appended to `logs/busHealth.log`)
- Scheduled / cron health check with email alert if `overall == "error"`
- Checking `llcReceivables` and `llcPayables` cross-balance against GL

---

## 10. Implementation Effort

| Item | Effort |
|---|---|
| `util/llcBusHealthAgent.py` — env + git + file checks | 2 hr |
| eSession dirty-file detection | 1 hr |
| Flask route + 403 guard | 30 min |
| `llcBusHealth.html` template | 1.5 hr |
| Nav entry + active highlight | 15 min |
| **Total** | **~5 hr** |
