"""Phase 3B tests — operator introspection CLI commands.

Proves:
1. `runs` command returns structured table output (RUN_ID, CAPABILITY, STATUS, STARTED_AT)
2. `runs --limit N` respects the limit
3. `runs` with empty journal prints "No runs found." and exits 0
4. `journal latest` returns most recent record as JSON
5. `journal latest` with empty journal prints "Journal is empty." and exits 0
6. `inspect <run_id>` returns correct record as JSON
7. `inspect <unknown_run_id>` exits 1 and prints "Run <run_id> not found."
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os.cli import cmd_runs, cmd_journal_latest, cmd_inspect, find_project_root
from agent_os.contracts.models import ExecutionJournalRecord
from agent_os.journal import ExecutionJournal


# ── Helpers ───────────────────────────────────────────────────

def _make_record(run_id: str | None = None, **overrides) -> ExecutionJournalRecord:
    now = datetime.now(timezone.utc)
    base = dict(
        journal_id=uuid.uuid4().hex,
        run_id=run_id or f"run_{uuid.uuid4().hex[:8]}",
        agent_id="clawbot-sandbox",
        capability="web.search",
        runtime_target="openclaw",
        requested_at=now,
        finished_at=now,
        status="succeeded",
        lifecycle_trace=[{"from": "planning", "to": "succeeded", "reason": "task_complete"}],
    )
    base.update(overrides)
    return ExecutionJournalRecord(**base)


def _write_record(journal: ExecutionJournal, record: ExecutionJournalRecord) -> None:
    journal.write(record)


def _args(**kwargs):
    """Build a minimal argparse.Namespace from kwargs."""
    import argparse
    ns = argparse.Namespace(**kwargs)
    return ns


# ── 1. `runs` command — structured table output ───────────────

class TestRunsCommand:

    def test_runs_empty_journal_prints_no_runs_found(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        journal = ExecutionJournal(journal_dir)
        # empty — no writes

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            rc = cmd_runs(args)

        captured = capsys.readouterr()
        assert rc == 0
        assert "No runs found." in captured.out

    def test_runs_returns_zero_exit_code(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            rc = cmd_runs(args)

        assert rc == 0

    def test_runs_prints_run_id_in_output(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        record = _make_record(run_id="run_aabbccdd")
        j.write(record)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            cmd_runs(args)

        captured = capsys.readouterr()
        assert "run_aabbccdd" in captured.out

    def test_runs_prints_capability_in_output(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(capability="web.search"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            cmd_runs(args)

        captured = capsys.readouterr()
        assert "web.search" in captured.out

    def test_runs_prints_status_in_output(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="timed_out"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            cmd_runs(args)

        captured = capsys.readouterr()
        assert "timed_out" in captured.out

    def test_runs_prints_header_columns(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            cmd_runs(args)

        captured = capsys.readouterr()
        assert "RUN_ID" in captured.out
        assert "CAPABILITY" in captured.out
        assert "STATUS" in captured.out
        assert "STARTED_AT" in captured.out


# ── 2. `runs --limit N` respects the limit ────────────────────

class TestRunsLimit:

    def test_runs_limit_restricts_output(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        for i in range(7):
            j.write(_make_record(run_id=f"run_{i:08x}"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=3)
            cmd_runs(args)

        captured = capsys.readouterr()
        # Count how many run_ lines appear (excluding header)
        run_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(run_lines) == 3

    def test_runs_default_limit_is_10(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        for i in range(15):
            j.write(_make_record(run_id=f"run_{i:08x}"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=10)
            cmd_runs(args)

        captured = capsys.readouterr()
        run_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(run_lines) == 10

    def test_runs_limit_1_returns_one_row(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        for i in range(5):
            j.write(_make_record(run_id=f"run_{i:08x}"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args(limit=1)
            cmd_runs(args)

        captured = capsys.readouterr()
        run_lines = [l for l in captured.out.splitlines() if l.strip().startswith("run_")]
        assert len(run_lines) == 1


# ── 3. `journal latest` ───────────────────────────────────────

class TestJournalLatestCommand:

    def test_journal_latest_empty_prints_journal_is_empty(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args()
            rc = cmd_journal_latest(args)

        captured = capsys.readouterr()
        assert rc == 0
        assert "Journal is empty." in captured.out

    def test_journal_latest_returns_json(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_latest01"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args()
            rc = cmd_journal_latest(args)

        captured = capsys.readouterr()
        assert rc == 0
        # Output must be valid JSON
        data = json.loads(captured.out)
        assert data["run_id"] == "run_latest01"

    def test_journal_latest_returns_most_recent(self, tmp_path, capsys):
        import time
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_first000"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_second00"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args()
            cmd_journal_latest(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["run_id"] == "run_second00"

    def test_journal_latest_json_has_required_fields(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            args = _args()
            cmd_journal_latest(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        for field in ("run_id", "journal_id", "agent_id", "status", "requested_at", "finished_at"):
            assert field in data, f"Missing field: {field}"

    def test_journal_latest_exits_zero(self, tmp_path, capsys):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli.ExecutionJournal", lambda d: ExecutionJournal(journal_dir))
            rc = cmd_journal_latest(_args())

        assert rc == 0


# ── 4. `inspect <run_id>` ─────────────────────────────────────

class TestInspectCommand:

    def test_inspect_known_run_id_returns_json(self, tmp_path, capsys):
        # cmd_inspect reads from <project_root>/.agent_os/journal/
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_aabbccdd"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = _args(run_id="run_aabbccdd")
            rc = cmd_inspect(args)

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_aabbccdd"

    def test_inspect_unknown_run_id_exits_1(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = _args(run_id="run_nosuchrun")
            rc = cmd_inspect(args)

        assert rc == 1

    def test_inspect_unknown_run_id_prints_not_found(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = _args(run_id="run_nosuchrun")
            cmd_inspect(args)

        captured = capsys.readouterr()
        assert "run_nosuchrun" in captured.out
        assert "not found" in captured.out.lower()

    def test_inspect_returns_full_record(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        record = _make_record(
            run_id="run_fullcheck",
            capability="tasks.read",
            status="failed",
        )
        j.write(record)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = _args(run_id="run_fullcheck")
            cmd_inspect(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["capability"] == "tasks.read"
        assert data["status"] == "failed"
        assert data["agent_id"] == "clawbot-sandbox"

    def test_inspect_json_includes_lifecycle_trace(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_lifecycle1"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = _args(run_id="run_lifecycle1")
            cmd_inspect(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "lifecycle_trace" in data
        assert isinstance(data["lifecycle_trace"], list)
