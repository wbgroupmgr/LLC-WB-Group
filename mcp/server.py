"""
mcp/server.py
-------------
MCP server entry point for llcRentalTracker.

Exposes four skill domains:
    accounting   — ledger queries, balance sheet, GL, income statement
    cpa_analysis — ratio analysis, trend detection, memo generation
    irs_tax      — Form 1065, K-1, Form 8825, Form 4562 population
    webapp       — Flask session management, live data access

Usage:
    python -m mcp.server --llcName WBGroupLLC

MCP library selection is deferred — stub imports below will be replaced
once the MCP framework is chosen (e.g. mcp-python, fastmcp, or custom).
"""

import argparse
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from ledger import setup_paths as _sp
from mcp.skills import accounting, cpa_analysis, irs_tax, webapp


def build_server(llc_name: str, year: int):
    """Construct and return the MCP server instance."""
    _sp.load_config(llc_name, year)

    # TODO: replace with chosen MCP framework initialisation
    raise NotImplementedError(
        "MCP framework not yet selected. "
        "Implement build_server() once mcp library is chosen (Task 5)."
    )


def main():
    ap = argparse.ArgumentParser(prog="mcp.server",
                                 description="llcRentalTracker MCP server")
    ap.add_argument("--llcName", required=True, metavar="NAME",
                    help="LLC name, e.g. WBGroupLLC")
    ap.add_argument("--year", type=int, required=True, metavar="YEAR",
                    help="Fiscal year, e.g. 2025")
    args = ap.parse_args()
    server = build_server(args.llcName, args.year)
    server.run()


if __name__ == "__main__":
    main()
