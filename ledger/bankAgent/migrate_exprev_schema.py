"""
migrate_exprev_schema.py  —  P0 one-time migration for llcExpRev_*.json

Converts flat list → {"records": [...], "LogHistory": []}
Also renames refDB "llcBank" → "llcBank-Manual" for all existing records
(they were manually entered from the bank statement, not imported by BankAgent).

Run once from the repo root:
    python3 -m ledger.bankAgent.migrate_exprev_schema
"""

import json
import shutil
import datetime
from pathlib import Path

from ledger import setup_paths


def migrate(llc_name: str = "WBGroupLLC") -> None:
    setup_paths.load_bootstrap(llc_name)
    fp = setup_paths.ACCTS_DIR / f"llcExpRev_{setup_paths.DATA_NAME}.json"

    with open(fp, "r") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and "records" in raw:
        print(f"[migrate] {fp.name} already in new format — nothing to do.")
        return

    if not isinstance(raw, list):
        raise ValueError(f"[migrate] unexpected type {type(raw)} in {fp}")

    # Backup before touching
    bk = fp.with_suffix(f".bak_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    shutil.copy2(fp, bk)
    print(f"[migrate] backup → {bk.name}")

    # refDB: "llcBank" (manual) → "llcBank-Manual"
    updated = 0
    for rec in raw:
        if rec.get("refDB") == "llcBank":
            rec["refDB"] = "llcBank-Manual"
            updated += 1

    new_data = {"records": raw, "LogHistory": []}
    with open(fp, "w") as f:
        json.dump(new_data, f, indent=4)

    print(f"[migrate] {fp.name}: {len(raw)} records wrapped, {updated} refDB updated → llcBank-Manual")


if __name__ == "__main__":
    import sys
    migrate(sys.argv[1] if len(sys.argv) > 1 else "WBGroupLLC")
