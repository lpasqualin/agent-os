"""Phase 4A tests — filtered run queries and operator summary view.

Proves:
1. --status filter returns only matching rows (normalized comparison)
2. --capability filter returns only matching rows
3. --status + --capability combined filter (AND logic)
4. --status with no matches prints "No runs found."
5. --summary outputs correct aggregate counts
6. --summary with empty journal outputs "No runs found."
7. Status normalization: raw journal values → canonical display values
8. --limit still respected after filtering
9. Unfiltered behavior unchanged (no regression)
"""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os.cli import (
    _normalize_status,
    _filter_rows,
    _cmd_runs_summary,
    cmd_runs,
)
from agent_os.contracts.models import ExecutionJournalRecord
from agent_os.journal import ExecutionJournal


# ── Helpers ───────────────────────────────────────────────────

def _make_record(
    run_id: str | None = None,
    status: str = "succeeded",
    capability: str = "web.search",
    **overrides,
) -> ExecutionJournalRecord:
    now = datetime.now(timezone.utc)
    base = dict(
        journal_id=uuid.uuid4().hex,
        run_id=run_id or f"run_{uuid.uuid4().hex[:8]}",
        agent_id="clawbot-sandbox",
        capability=capability,
        runtime_target="openclaw",
        requested_at=now,
        finished_at=now,
        status=status,
    )
    base.update(overrides)
    return ExecutionJournalRecord(**base)


def _args(**kwargs) -> argparse.Namespace:
    defaults = dict(limit=10, status=None, capability=None, summary=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def journal_dir(tmp_path):
    d = tmp_path / "journal"
    d.mkdir()
    return d


@pytest.fixture
def populated_journal(journal_dir):
    """Write a controlled set of records for filter testing."""
    j = ExecutionJournal(journal_dir)
    # 3 succeeded / web.search
    for i in range(3):
        j.write(_make_record(run_id=f"run_ws_ok_{i:03}", status="succeeded", capability="web.search"))
        time.sleep(0.01)
    # 2 failed / web.search
    for i in range(2):
        j.write(_make_record(run_id=f"run_ws_fail_{i:03}", status="failed", capability="web.search"))
        time.sleep(0.01)
    # 2 timed_out / tasks.read
    for i in range(2):
        j.write(_make_record(run_id=f"run_tr_to_{i:03}", status="timed_out", capability="tasks.read"))
        time.sleep(0.01)
    # 1 rejected / tasks.read
    j.write(_make_record(run_id="run_tr_rej_000", status="rejected", capability="tasks.read"))
    return journal_dir


# ── 1. Status normalization ───────────────────────────────────

class TestNormalizeStatus:
    """_normalize_status maps raw journal values to canonical values."""

    def test_succeeded_maps_to_success(self):
        assert _normalize_status("succeeded") == "SUCCESS"

    def test_success_maps_to_success(self):
        assert _normalize_status("success") == "SUCCESS"

    def test_failed_maps_to_failed(self):
        assert _normalize_status("failed") == "FAILED"

    def test_canceled_maps_to_failed(self):
        assert _normalize_status("canceled") == "FAILED"

    def test_cancelled_maps_to_failed(self):
        assert _normalize_status("cancelled") == "FAILED"

    def test_rejected_maps_to_capability_error(self):
        assert _normalize_status("rejected") == "CAPABILITY_ERROR"

    def test_timed_out_maps_to_timeout(self):
        assert _normalize_status("timed_out") == "TIMEOUT"

    def test_timeout_maps_to_timeout(self):
        assert _normalize_status("timeout") == "TIMEOUT"

    def test_unknown_maps_to_failed(self):
        assert _normalize_status("some_unknown_status") == "FAILED"

    def test_empty_string_maps_to_failed(self):
        assert _normalize_status("") == "FAILED"

    def test_case_insensitive_succeeded(self):
        assert _normalize_status("SUCCEEDED") == "SUCCESS"

    def test_case_insensitive_timed_out(self):
        assert _normalize_status("TIMED_OUT") == "TIMEOUT"

    def test_case_insensitive_rejected(self):
        assert _normalize_status("REJECTED") == "CAPABILITY_ERROR"

    def test_canonical_values_round_trip(self):
        """Canonical values are idempotent through normalization."""
        assert _normalize_status("SUCCESS") == "SUCCESS"
        assert _normalize_status("FAILED") == "FAILED"
        assert _normalize_status("CAPABILITY_ERROR") == "CAPABILITY_ERROR"
        assert _normalize_status("TIMEOUT") == "TIMEOUT"


# ── 2. _filter_rows logic ─────────────────────────────────────

class TestFilterRows:
    """_filter_rows applies AND logic correctly."""

    def _make_rows(self):
        return [
            {"run_id": "r1", "status": "succeeded",  "capability": "web.search"},
            {"run_id": "r2", "status": "failed",      "capability": "web.search"},
            {"run_id": "r3", "status": "timed_out",   "capability": "tasks.read"},
            {"run_id": "r4", "status": "rejected",    "capability": "tasks.read"},
            {"run_id": "r5", "status": "succeeded",   "capability": "tasks.read"},
        ]

    def test_no_filters_returns_all(self):
        rows = self._make_rows()
        assert _filter_rows(rows, None, None) == rows

    def test_status_filter_succeeded(self):
        result = _filter_rows(self._make_rows(), "succeeded", None)
        assert len(result) == 2
        assert all(_normalize_status(r["status"]) == "SUCCESS" for r in result)

    def test_status_filter_failed(self):
        result = _filter_rows(self._make_rows(), "failed", None)
        assert len(result) == 1
        assert result[0]["run_id"] == "r2"

    def test_status_filter_timeout(self):
        result = _filter_rows(self._make_rows(), "timeout", None)
        assert len(result) == 1
        assert result[0]["run_id"] == "r3"

    def test_status_filter_capability_error(self):
        result = _filter_rows(self._make_rows(), "capability_error", None)
        assert len(result) == 1
        assert result[0]["run_id"] == "r4"

    def test_capability_filter(self):
        result = _filter_rows(self._make_rows(), None, "web.search")
        assert len(result) == 2
        assert all(r["capability"] == "web.search" for r in result)

    def test_capability_filter_case_insensitive(self):
        result = _filter_rows(self._make_rows(), None, "WEB.SEARCH")
        assert len(result) == 2

    def test_combined_filter_and_logic(self):
        result = _filter_rows(self._make_rows(), "succeeded", "tasks.read")
        assert len(result) == 1
        assert result[0]["run_id"] == "r5"

    def test_combined_filter_no_match(self):
        result = _filter_rows(self._make_rows(), "failed", "tasks.read")
        assert len(result) == 0

    def test_filter_timed_out_alias(self):
        """'timed_out' raw value matches --status timeout filter."""
        rows = [{"run_id": "x", "status": "timed_out", "capability": "web.search"}]
        assert len(_filter_rows(rows, "timeout", None)) == 1
        assert len(_filter_rows(rows, "timed_out", None)) == 1

    def test_filter_rejected_alias(self):
        """'rejected' raw value matches --status capability_error filter."""
        rows = [{"run_id": "x", "status": "rejected", "capability": "web.search"}]
        assert len(_filter_rows(rows, "capability_error", None)) == 1


# ── 3. cmd_runs with filters ──────────────────────────────────

class TestCmdRunsFiltered:
    """cmd_runs prints correct filtered output."""

    def test_status_filter_shows_only_matching(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="succeeded"))

        captured = capsys.readouterr()
        assert rc == 0
        # All displayed rows should have raw "succeeded" status
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 3
        assert all("succeeded" in l for l in data_lines)

    def test_status_filter_failed(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="failed"))

        captured = capsys.readouterr()
        assert rc == 0
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 2
        assert all("failed" in l for l in data_lines)

    def test_capability_filter(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(capability="web.search"))

        captured = capsys.readouterr()
        assert rc == 0
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 5  # 3 ok + 2 fail
        assert all("web.search" in l for l in data_lines)

    def test_combined_status_and_capability_filter(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="timeout", capability="tasks.read"))

        captured = capsys.readouterr()
        assert rc == 0
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 2
        # Filter matched timed_out records; raw value shown in table
        assert all("timed_out" in l for l in data_lines)
        assert all("tasks.read" in l for l in data_lines)

    def test_status_filter_no_match_prints_no_runs_found(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="capability_error", capability="web.search"))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No runs found." in captured.out

    def test_limit_respected_after_filter(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="succeeded", limit=2))

        captured = capsys.readouterr()
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 2

    def test_timeout_filter_alias(self, populated_journal, capsys):
        """--status timeout matches timed_out journal values; table shows raw value."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(status="timeout"))

        captured = capsys.readouterr()
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 2
        assert all("timed_out" in l for l in data_lines)

    def test_no_filters_shows_raw_status(self, populated_journal, capsys):
        """Unfiltered table shows raw journal status strings (normalization is
        for filters and --summary only, to preserve existing display behavior)."""
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args())

        captured = capsys.readouterr()
        assert rc == 0
        # Raw status values appear in the table
        assert any(v in captured.out for v in ("succeeded", "failed", "timed_out", "rejected"))


# ── 4. Summary view ───────────────────────────────────────────

class TestRunsSummary:
    """--summary shows aggregate counts and bookmarks."""

    def test_summary_empty_journal_prints_no_runs_found(self, journal_dir, capsys):
        j = ExecutionJournal(journal_dir)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: journal_dir.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(journal_dir),
            )
            rc = cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No runs found." in captured.out

    def test_summary_shows_total(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        assert "Total runs:" in captured.out
        assert "8" in captured.out  # 3+2+2+1 = 8 records

    def test_summary_correct_success_count(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        # 3 succeeded → SUCCESS: 3
        lines = {l.split(":")[0].strip(): l.split(":")[-1].strip()
                 for l in captured.out.splitlines() if ":" in l}
        assert lines.get("SUCCESS") == "3"

    def test_summary_correct_failed_count(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        lines = {l.split(":")[0].strip(): l.split(":")[-1].strip()
                 for l in captured.out.splitlines() if ":" in l}
        assert lines.get("FAILED") == "2"

    def test_summary_correct_capability_error_count(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        lines = {l.split(":")[0].strip(): l.split(":")[-1].strip()
                 for l in captured.out.splitlines() if ":" in l}
        assert lines.get("CAPABILITY_ERROR") == "1"

    def test_summary_correct_timeout_count(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        lines = {l.split(":")[0].strip(): l.split(":")[-1].strip()
                 for l in captured.out.splitlines() if ":" in l}
        assert lines.get("TIMEOUT") == "2"

    def test_summary_shows_most_recent_run(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        assert "Most recent run:" in captured.out

    def test_summary_shows_last_failure(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        assert "Last failure:" in captured.out

    def test_summary_exits_zero(self, populated_journal, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: populated_journal.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(populated_journal),
            )
            rc = cmd_runs(_args(summary=True))

        assert rc == 0

    def test_summary_all_success_no_last_failure_line(self, journal_dir, capsys):
        """When all runs succeed, Last failure line is absent."""
        j = ExecutionJournal(journal_dir)
        for i in range(3):
            j.write(_make_record(run_id=f"run_ok_{i:03}", status="succeeded"))
            time.sleep(0.01)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: journal_dir.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(journal_dir),
            )
            cmd_runs(_args(summary=True))

        captured = capsys.readouterr()
        assert "Last failure:" not in captured.out


# ── 5. Unfiltered regression guard ───────────────────────────

class TestUnfilteredRegression:
    """Existing unfiltered behavior is unchanged."""

    def test_no_filters_default_limit_10(self, journal_dir, capsys):
        j = ExecutionJournal(journal_dir)
        for i in range(15):
            j.write(_make_record(run_id=f"run_{i:08x}"))
            time.sleep(0.01)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: journal_dir.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(journal_dir),
            )
            cmd_runs(_args())

        captured = capsys.readouterr()
        data_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(data_lines) == 10

    def test_empty_journal_prints_no_runs_found(self, journal_dir, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: journal_dir.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(journal_dir),
            )
            rc = cmd_runs(_args())

        captured = capsys.readouterr()
        assert rc == 0
        assert "No runs found." in captured.out

    def test_header_columns_present(self, journal_dir, capsys):
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: journal_dir.parent)
            mp.setattr(
                "agent_os.cli.ExecutionJournal",
                lambda d: ExecutionJournal(journal_dir),
            )
            cmd_runs(_args())

        captured = capsys.readouterr()
        assert "RUN_ID" in captured.out
        assert "CAPABILITY" in captured.out
        assert "STATUS" in captured.out
        assert "STARTED_AT" in captured.out
