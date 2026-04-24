#!/usr/bin/env python3
"""Agent OS — Journal migration script.

Moves legacy flat journal files (``<journal_dir>/<run_id>.json``) into
the Phase A1 partitioned layout (``<journal_dir>/YYYY/MM/<run_id>.json``).

Usage:
    python scripts/migrate_journal.py [--journal-dir PATH] [--dry-run]

    --journal-dir PATH   Root of the journal directory.
                         Defaults to .agent_os/journal relative to CWD.
    --dry-run            Print what would be moved without moving anything.

Exit codes:
    0  — success (zero or more files moved)
    1  — one or more files could not be processed (details printed to stderr)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate flat Agent OS journal files to YYYY/MM partitions."
    )
    parser.add_argument(
        "--journal-dir",
        default=".agent_os/journal",
        help="Root journal directory (default: .agent_os/journal)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned moves without executing them.",
    )
    args = parser.parse_args()

    journal_dir = Path(args.journal_dir).expanduser().resolve()

    if not journal_dir.is_dir():
        print(f"[error] Journal directory does not exist: {journal_dir}", file=sys.stderr)
        return 1

    if args.dry_run:
        return _dry_run(journal_dir)

    # Real run
    from agent_os.journal import migrate_flat_to_partitioned
    report = migrate_flat_to_partitioned(journal_dir)

    print(f"Migration complete.")
    print(f"  Moved  : {report['moved']}")
    print(f"  Errors : {report['errors']}")

    return 0 if report["errors"] == 0 else 1


def _dry_run(journal_dir: Path) -> int:
    import json
    from datetime import datetime

    flat_files = [
        f for f in journal_dir.iterdir()
        if f.is_file() and f.suffix == ".json"
    ]

    if not flat_files:
        print("No flat files found — nothing to migrate.")
        return 0

    print(f"DRY RUN — {len(flat_files)} file(s) would be processed:\n")
    errors = 0

    for f in flat_files:
        try:
            data = json.loads(f.read_text())
            ts_str = data.get("requested_at")
            if not ts_str:
                raise ValueError("missing requested_at")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            dest = journal_dir / f"{ts.year:04d}" / f"{ts.month:02d}" / f.name
            print(f"  {f.name}  →  {dest.relative_to(journal_dir)}")
        except Exception as exc:
            print(f"  [ERROR] {f.name}: {exc}", file=sys.stderr)
            errors += 1

    print()
    if errors:
        print(f"{errors} file(s) cannot be migrated (see errors above).", file=sys.stderr)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
