"""Phase 4C tests — failure analysis surfacing in inspect output.

Design: failure summary → stderr (human-readable diagnostic overlay).
        full JSON      → stdout (machine-parseable, unchanged from prior phases).

Proves:
1. inspect on a failed run shows failure summary block on stderr before JSON on stdout
2. inspect on a SUCCESS run does NOT show failure summary block
3. failure summary contains correct status (normalized), capability, runtime, agent
4. duration is calculated correctly when both timestamps present
5. duration shows "unknown" when started_at is missing
6. each failure status maps to the correct human-readable reason
7. missing optional fields (error_message, policy_decision) are skipped gracefully
8. --latest shortcut shows failure summary when latest run is a failure
9. --last-failure shortcut always shows failure summary
"""

import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from agent_os.cli import (
    cmd_inspect,
    _format_duration,
    _print_failure_summary,
    find_project_root,
)
from agent_os.contracts.models import ExecutionJournalRecord
from agent_os.journal import ExecutionJournal


# ── Helpers ───────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_record(run_id: str | None = None, **overrides) -> ExecutionJournalRecord:
    now = _now()
    base = dict(
        journal_id=uuid.uuid4().hex,
        run_id=run_id or f"run_{uuid.uuid4().hex[:8]}",
        agent_id="clawbot-sandbox",
        capability="web.search",
        runtime_target="openclaw",
        requested_at=now,
        started_at=now,
        finished_at=now + timedelta(seconds=30),
        status="succeeded",
        lifecycle_trace=[{"from": "planning", "to": "succeeded", "reason": "task_complete"}],
    )
    base.update(overrides)
    return ExecutionJournalRecord(**base)


def _args(**kwargs):
    import argparse
    defaults = dict(run_id=None, latest=False, last_failure=False)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── 1. Failure summary block present for failed runs ──────────

class TestFailureSummaryPresence:

    def test_failed_run_shows_failure_summary_on_stderr(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_fail0001"))

        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err

    def test_failure_summary_on_stderr_json_on_stdout(self, tmp_path, capsys):
        """Summary on stderr, JSON on stdout — different streams."""
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0002", status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_fail0002"))

        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail0002"

    def test_timed_out_shows_failure_summary(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_timeout1", status="timed_out"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_timeout1"))

        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err

    def test_rejected_shows_failure_summary(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_reject01", status="rejected"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_reject01"))

        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err

    def test_full_json_on_stdout_after_summary(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0003", status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_fail0003"))

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail0003"


# ── 2. No failure summary for SUCCESS ─────────────────────────

class TestNoSummaryForSuccess:

    def test_succeeded_run_no_failure_summary_on_stderr(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_success1", status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_success1"))

        captured = capsys.readouterr()
        assert "Failure Summary" not in captured.err

    def test_succeeded_run_json_on_stdout_is_valid(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_success2", status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id="run_success2"))

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["run_id"] == "run_success2"


# ── 3. Summary contains correct fields ────────────────────────

class TestSummaryFieldContent:

    def test_summary_shows_normalized_status(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="timed_out"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "TIMEOUT" in captured.err

    def test_summary_shows_capability(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", capability="tasks.read"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "tasks.read" in captured.err

    def test_summary_shows_runtime_target(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", runtime_target="openclaw"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "openclaw" in captured.err

    def test_summary_shows_agent_id(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", agent_id="clawbot-sandbox"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "clawbot-sandbox" in captured.err


# ── 4. Duration calculation ────────────────────────────────────

class TestFormatDuration:

    def test_duration_seconds_only(self):
        start = "2026-03-20T10:00:00+00:00"
        end   = "2026-03-20T10:00:30.200000+00:00"
        result = _format_duration(start, end)
        assert result == "30.2s"

    def test_duration_minutes_and_seconds(self):
        start = "2026-03-20T10:00:00+00:00"
        end   = "2026-03-20T10:02:15+00:00"
        result = _format_duration(start, end)
        assert result == "2m 15.0s"

    def test_duration_zero_seconds(self):
        ts = "2026-03-20T10:00:00+00:00"
        result = _format_duration(ts, ts)
        assert result == "0.0s"

    def test_duration_unknown_when_started_at_none(self):
        result = _format_duration(None, "2026-03-20T10:00:30+00:00")
        assert result == "unknown"

    def test_duration_unknown_when_finished_at_none(self):
        result = _format_duration("2026-03-20T10:00:00+00:00", None)
        assert result == "unknown"

    def test_duration_unknown_when_both_none(self):
        result = _format_duration(None, None)
        assert result == "unknown"

    def test_duration_shown_in_summary_on_stderr(self, tmp_path, capsys):
        now = _now()
        finished = now + timedelta(seconds=30, milliseconds=200)
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", started_at=now, finished_at=finished))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "Duration:" in captured.err

    def test_duration_unknown_when_started_at_missing_from_record(self, tmp_path, capsys):
        now = _now()
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", started_at=None, finished_at=now))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "unknown" in captured.err


# ── 5. Reason mapping per status ──────────────────────────────

class TestReasonMapping:

    def _get_stderr(self, status: str, tmp_path, capsys) -> str:
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status=status))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        return capsys.readouterr().err

    def test_timeout_reason(self, tmp_path, capsys):
        err = self._get_stderr("timed_out", tmp_path, capsys)
        assert "Runtime execution timed out" in err

    def test_failed_reason(self, tmp_path, capsys):
        err = self._get_stderr("failed", tmp_path, capsys)
        assert "Runtime returned a failure result" in err

    def test_rejected_reason(self, tmp_path, capsys):
        err = self._get_stderr("rejected", tmp_path, capsys)
        assert "Capability not supported by runtime adapter" in err


# ── 6. Missing optional fields: no crash ──────────────────────

class TestMissingFieldsGraceful:

    def test_no_error_message_no_crash(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed"))  # error_message defaults to None

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            rc = cmd_inspect(_args(run_id=rows[0]["run_id"]))

        assert rc == 0

    def test_no_policy_decision_no_crash(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed"))  # policy_decision defaults to None

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            rc = cmd_inspect(_args(run_id=rows[0]["run_id"]))

        assert rc == 0

    def test_error_message_shown_when_present(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", error_message="subprocess timeout after 30s"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "subprocess timeout after 30s" in captured.err

    def test_policy_decision_shown_when_present(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="rejected", policy_decision="deny"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            cmd_inspect(_args(run_id=rows[0]["run_id"]))

        captured = capsys.readouterr()
        assert "deny" in captured.err

    def test_no_crash_when_capability_none(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed", capability=None))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rows = ExecutionJournal(journal_dir).list_runs(limit=1)
            rc = cmd_inspect(_args(run_id=rows[0]["run_id"]))

        assert rc == 0


# ── 7. Shortcut paths show failure summary ────────────────────

class TestShortcutSummary:

    def test_latest_shows_failure_summary_when_failed(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(latest=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "Failure Summary" in captured.err

    def test_latest_no_summary_when_succeeded(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(latest=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "Failure Summary" not in captured.err

    def test_last_failure_always_shows_failure_summary(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="timed_out"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "Failure Summary" in captured.err

    def test_last_failure_json_on_stdout_is_valid(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail_lf1", status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail_lf1"


# ── 8. _print_failure_summary unit tests ──────────────────────

class TestPrintFailureSummaryUnit:

    def test_success_data_writes_nothing_to_stderr(self, capsys):
        data = {
            "status": "succeeded",
            "capability": "web.search",
            "runtime_target": "openclaw",
            "agent_id": "clawbot-sandbox",
            "started_at": "2026-03-20T10:00:00+00:00",
            "finished_at": "2026-03-20T10:00:30+00:00",
        }
        _print_failure_summary(data)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_failure_data_writes_summary_to_stderr(self, capsys):
        data = {
            "status": "failed",
            "capability": "web.search",
            "runtime_target": "openclaw",
            "agent_id": "clawbot-sandbox",
            "started_at": "2026-03-20T10:00:00+00:00",
            "finished_at": "2026-03-20T10:00:30+00:00",
        }
        _print_failure_summary(data)
        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err
        assert "FAILED" in captured.err

    def test_empty_dict_no_crash(self, capsys):
        _print_failure_summary({"status": "failed"})
        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err

    def test_all_optional_fields_none_no_crash(self, capsys):
        data = {
            "status": "timed_out",
            "capability": None,
            "runtime_target": None,
            "agent_id": None,
            "started_at": None,
            "finished_at": None,
            "error_message": None,
            "policy_decision": None,
        }
        _print_failure_summary(data)
        captured = capsys.readouterr()
        assert "Failure Summary" in captured.err
        assert "unknown" in captured.err  # duration
