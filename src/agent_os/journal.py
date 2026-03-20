"""Execution journal — append-only, file-based run records.

One JSON file per chassis execution at:
    <journal_dir>/<run_id>.json

No external database. Directory is created on first write.
Write failures are silent — logged to stderr but never propagate to the chassis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_os.contracts.models import ExecutionJournalRecord


_DEFAULT_JOURNAL_DIR = Path(".agent_os") / "journal"


class ExecutionJournal:
    """File-based execution journal.

    Args:
        journal_dir: Directory to store run records.
                     Defaults to ``.agent_os/journal/`` relative to CWD at write time.
    """

    def __init__(self, journal_dir: str | Path | None = None):
        self._journal_dir: Path | None = Path(journal_dir) if journal_dir else None

    # ── Private ──────────────────────────────────────────────

    def _resolve_dir(self) -> Path:
        d = self._journal_dir if self._journal_dir is not None else _DEFAULT_JOURNAL_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── Write ─────────────────────────────────────────────────

    def write(self, record: ExecutionJournalRecord) -> None:
        """Persist record to disk.

        Silently swallows any I/O failure — the chassis must never crash
        because of a journal write.
        """
        try:
            d = self._resolve_dir()
            path = d / f"{record.run_id}.json"
            path.write_text(record.model_dump_json(indent=2))
        except Exception as exc:  # noqa: BLE001
            print(
                f"[agent_os.journal] WARNING: failed to write journal record "
                f"{record.run_id}: {exc}",
                file=sys.stderr,
            )

    # ── Read ──────────────────────────────────────────────────

    def read_latest(self) -> ExecutionJournalRecord | None:
        """Return the most recently written record, or None if journal is empty."""
        try:
            d = self._resolve_dir()
            files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not files:
                return None
            return ExecutionJournalRecord.model_validate_json(files[0].read_text())
        except Exception:
            return None

    def list_runs(self, limit: int = 20) -> list[dict]:
        """Return summary rows for the most recent `limit` runs, newest first.

        Each row contains: run_id, status, agent_id, capability,
        requested_at, finished_at, duration_ms (from metadata).
        """
        try:
            d = self._resolve_dir()
            files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return []

        rows = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                rows.append({
                    "run_id":       data.get("run_id", "?"),
                    "status":       data.get("status", "?"),
                    "agent_id":     data.get("agent_id", "?"),
                    "capability":   data.get("capability", "?"),
                    "requested_at": data.get("requested_at", "?"),
                    "finished_at":  data.get("finished_at", "?"),
                    "duration_ms":  data.get("metadata", {}).get("duration_ms"),
                })
            except Exception:
                continue
        return rows
