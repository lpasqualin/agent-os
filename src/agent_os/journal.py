"""Execution journal — append-only, file-based run records.

Phase A1: Partitioned storage.

Layout:
    <journal_dir>/YYYY/MM/<run_id>.json

No external database. Directory is created on first write.
Write failures are silent — logged to stderr but never propagate to the chassis.

Backward-compatible with flat-file layouts via migrate_flat_to_partitioned().
"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Iterator

from agent_os.contracts.models import ExecutionJournalRecord


_DEFAULT_JOURNAL_DIR = Path(".agent_os") / "journal"

# CSV columns emitted by export(fmt="csv")
_CSV_COLUMNS = [
    "run_id", "agent_id", "capability", "status",
    "requested_at", "finished_at", "runtime_target",
    "policy_decision", "error_message",
]


class ExecutionJournal:
    """File-based execution journal with YYYY/MM partition layout.

    Args:
        journal_dir: Directory to store run records.
                     Defaults to ``.agent_os/journal/`` relative to CWD at write time.
    """

    def __init__(self, journal_dir: str | Path | None = None):
        self._journal_dir: Path | None = Path(journal_dir) if journal_dir else None

    # ── Private ───────────────────────────────────────────────

    def _resolve_dir(self) -> Path:
        d = self._journal_dir if self._journal_dir is not None else _DEFAULT_JOURNAL_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _all_files(self) -> list[Path]:
        """Return all *.json files in the journal tree, newest-first by requested_at.

        Scans recursively to cover both partitioned (YYYY/MM/) and legacy flat files.
        When both a partitioned and a flat compat file exist for the same run_id,
        the partitioned copy is kept and the flat copy is suppressed to avoid duplicates.
        Ordering key is the ``requested_at`` field embedded in the record.
        Falls back to mtime for any record that cannot be parsed.
        """
        try:
            root = self._resolve_dir()
        except Exception:
            return []

        all_json: list[Path] = list(root.rglob("*.json"))
        if not all_json:
            return []

        # Deduplicate: prefer partitioned paths over flat compat files.
        seen: set[str] = set()
        unique: list[Path] = []
        for f in all_json:
            if f.parent != root and f.stem not in seen:
                seen.add(f.stem)
                unique.append(f)
        for f in all_json:
            if f.parent == root and f.stem not in seen:
                seen.add(f.stem)
                unique.append(f)
        all_json = unique

        def _sort_key(p: Path):
            try:
                data = json.loads(p.read_text())
                ts_str = data.get("requested_at")
                if ts_str:
                    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                pass
            return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

        return sorted(all_json, key=_sort_key, reverse=True)

    def _iter_records(
        self,
        *,
        since: date | None = None,
        until: date | None = None,
    ) -> Iterator[dict]:
        """Yield raw record dicts, optionally filtered by requested_at date."""
        for f in self._all_files():
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue

            if since is not None or until is not None:
                ts_str = data.get("requested_at", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                except Exception:
                    continue
                if since is not None and ts < since:
                    continue
                if until is not None and ts > until:
                    continue

            yield data

    # ── Write ─────────────────────────────────────────────────

    def write(self, record: ExecutionJournalRecord) -> None:
        """Persist record to YYYY/MM/<run_id>.json.

        Also writes a flat compatibility copy at <journal_dir>/<run_id>.json
        (only if it does not already exist) so that legacy consumers using
        glob("*.json") on the journal root continue to find records.

        Silently swallows any I/O failure — the chassis must never crash
        because of a journal write.
        """
        try:
            d = self._resolve_dir()
            ts = record.requested_at
            if ts is None:
                ts = datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            partition = d / f"{ts.year:04d}" / f"{ts.month:02d}"
            partition.mkdir(parents=True, exist_ok=True)
            dest = partition / f"{record.run_id}.json"
            payload = record.model_dump_json(indent=2)
            dest.write_text(payload)
            # Flat compatibility copy for legacy flat-file consumers (A1 compat layer).
            flat = d / f"{record.run_id}.json"
            if not flat.exists():
                flat.write_text(payload)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[agent_os.journal] WARNING: failed to write journal record "
                f"{record.run_id}: {exc}",
                file=sys.stderr,
            )

    # ── Read ──────────────────────────────────────────────────

    def read_latest(self) -> ExecutionJournalRecord | None:
        """Return the most recently written record, or None if journal is empty."""
        for f in self._all_files():
            try:
                return ExecutionJournalRecord.model_validate_json(f.read_text())
            except Exception:
                continue
        return None

    def find_record(self, run_id: str) -> ExecutionJournalRecord | None:
        """Locate a record by run_id, searching all partitions and flat files.

        O(n) scan — journal is audit storage, not a query engine.
        Stem match means we never need to know which partition a record is in.
        """
        try:
            root = self._resolve_dir()
        except Exception:
            return None

        for f in root.rglob("*.json"):
            if f.stem == run_id:
                try:
                    return ExecutionJournalRecord.model_validate_json(f.read_text())
                except Exception:
                    return None
        return None

    def find_record_path(self, run_id: str) -> Path | None:
        """Return the filesystem path for a run_id, or None if not found."""
        try:
            root = self._resolve_dir()
        except Exception:
            return None

        for f in root.rglob("*.json"):
            if f.stem == run_id:
                return f
        return None

    def list_runs(self, limit: int = 20) -> list[dict]:
        """Return summary rows for the most recent `limit` runs, newest first.

        Each row contains: run_id, status, agent_id, capability,
        requested_at, finished_at, duration_ms (from metadata).
        """
        rows: list[dict] = []
        for data in self._iter_records():
            if len(rows) >= limit:
                break
            rows.append({
                "run_id":       data.get("run_id", "?"),
                "status":       data.get("status", "?"),
                "agent_id":     data.get("agent_id", "?"),
                "capability":   data.get("capability", "?"),
                "requested_at": data.get("requested_at", "?"),
                "finished_at":  data.get("finished_at", "?"),
                "duration_ms":  data.get("metadata", {}).get("duration_ms"),
            })
        return rows

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return aggregate statistics over the entire journal.

        Returns dict with keys:
            total_runs  — int
            by_status   — dict[str, int]
            earliest    — str ISO timestamp | None
            latest      — str ISO timestamp | None
            disk_bytes  — int (total file sizes)
        """
        total = 0
        by_status: dict[str, int] = {}
        earliest: str | None = None
        latest_ts: str | None = None
        disk_bytes = 0

        for f in self._all_files():
            try:
                text = f.read_text()
                disk_bytes += len(text.encode())
                data = json.loads(text)
                total += 1
                status = data.get("status", "unknown")
                by_status[status] = by_status.get(status, 0) + 1
                ts = data.get("requested_at")
                if ts:
                    if earliest is None or ts < earliest:
                        earliest = ts
                    if latest_ts is None or ts > latest_ts:
                        latest_ts = ts
            except Exception:
                continue

        return {
            "total_runs": total,
            "by_status": by_status,
            "earliest": earliest,
            "latest": latest_ts,
            "disk_bytes": disk_bytes,
        }

    # ── Export ────────────────────────────────────────────────

    def export(
        self,
        fmt: str = "json",
        since: date | None = None,
        until: date | None = None,
    ) -> str:
        """Export journal records as JSON or CSV string.

        Args:
            fmt:   "json" or "csv"
            since: Include only records with requested_at >= this date.
            until: Include only records with requested_at <= this date.

        Returns:
            Serialized string in the requested format.
        """
        records = list(self._iter_records(since=since, until=until))

        if fmt == "json":
            return json.dumps(records, indent=2, default=str)

        if fmt == "csv":
            if not records:
                return ""
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf,
                fieldnames=_CSV_COLUMNS,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in records:
                writer.writerow({col: row.get(col, "") for col in _CSV_COLUMNS})
            return buf.getvalue()

        raise ValueError(f"Unsupported export format: {fmt!r}. Use 'json' or 'csv'.")


# ── Migration ─────────────────────────────────────────────────

def migrate_flat_to_partitioned(journal_dir: Path) -> dict:
    """One-time migration: move flat <run_id>.json files into YYYY/MM partitions.

    Only processes files directly inside ``journal_dir`` (not subdirectories),
    so it is safe to run on a partially-migrated or already-partitioned journal.

    Uses the ``requested_at`` field inside each record to determine the partition.
    Records without a parseable ``requested_at`` are left in place and counted
    as errors.

    Args:
        journal_dir: Root journal directory (may or may not exist).

    Returns:
        dict with keys:
            moved  — number of files successfully moved
            errors — number of files that could not be processed
    """
    moved = 0
    errors = 0

    if not journal_dir.is_dir():
        return {"moved": 0, "errors": 0}

    # Only flat files at the top level — not inside subdirs
    flat_files = [
        f for f in journal_dir.iterdir()
        if f.is_file() and f.suffix == ".json"
    ]

    for f in flat_files:
        try:
            data = json.loads(f.read_text())
            ts_str = data.get("requested_at")
            if not ts_str:
                raise ValueError("missing requested_at")

            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            dest_dir = journal_dir / f"{ts.year:04d}" / f"{ts.month:02d}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f.name
            if dest.exists():
                # Flat compat copy — partition already present; just remove it.
                f.unlink()
            else:
                f.rename(dest)
                moved += 1
        except Exception as exc:  # noqa: BLE001
            print(
                f"[agent_os.journal] migrate: could not process {f.name}: {exc}",
                file=sys.stderr,
            )
            errors += 1

    return {"moved": moved, "errors": errors}
