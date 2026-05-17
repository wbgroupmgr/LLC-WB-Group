# llcRentalTracker

Rental property accounting and tax tracker — Flask web app and MCP server for LLC rental businesses.

## Services

| Service | Description |
|---------|-------------|
| **Ledger** | Double-entry bookkeeping engine (assets, expenses, receivables, payables) |
| **Statements** | Balance Sheet, Income Statement, General Ledger — immutable, year-specific |
| **IRS Forms** | Form 1065, Schedule K-1, Form 8825, Form 4562 — PDF generation and fill |
| **Web UI** | Flask app for ledger entry, statement review, and IRS form management |
| **MCP Server** | Model Context Protocol server exposing accounting, CPA analysis, and IRS skills |

## Quick Start

```bash
# Configure a business (generates ~/.llcRentalTracker/<llcName>_config.json)
python wsCmd.py --newBus ~/path/to/LLC-Business-Repo

# Start the web server
python wsCmd.py --llcName WBGroupLLC --port 5000
```

## Business Configuration

Each LLC business the tracker manages has a config file at:

```
~/.llcRentalTracker/<llcName>_config.json
```

```json
{
  "llcName":   "WBGroupLLC",
  "bus_repo":  "~/GDrive/Family/Assets/LLC-WBGroup",
  "books_dir": "books",
  "year":      2025
}
```

The tracker derives all data paths from these four fields — no hardcoded paths.

## Package Layout

```
llcRentalTracker/
├── ledger/       # Double-entry engine (LLC, ledgerDB, COA, statements)
├── irs/          # IRS form builders + PDF population
├── F1065_K1/     # Form 1065 / K-1 tax workflow
├── ui/           # Flask views + Jinja2 templates
├── util/         # Session management, working DB, MultiTaskWS integration
├── tests/        # Test suite (stmtBS, stmtGL, stmtIS)
├── mcp/          # MCP server + skill definitions
├── wsCmd.py      # CLI: start/stop server, --newBus provisioning
└── wsgi.py       # Flask WSGI entry point
```

## Running Tests

```bash
python -m tests.test_stmtBS
python -m tests.test_stmtGL
python -m tests.test_stmtIS
```

## Related

- Business repo: `LLC-WBGroup` — ledger data, IRS forms, asset docs (separate repo)
- Platform: [pyMultiTaskWS](https://github.com/wbgroupmgr/pyMultiTaskWS) — multi-app web server
