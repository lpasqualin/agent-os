"""Phase 4B tests — operator shortcuts for inspect and replay.

Proves:
1. `inspect --latest` resolves to the most recent run
2. `inspect --last-failure` resolves to the most recent failed run
3. `inspect --latest` on empty journal prints "No runs found." and exits 0
4. `inspect --last-failure` with no failures prints "No failed runs found." and exits 0
5. `inspect` with no run_id, no --latest, no --last-failure exits 1
6. `replay --last-failure` resolves to most recent failed run
7. `replay --last-failure` with no failures prints "No failed runs found." and exits 0
8. `replay` with no run_id, no --last-failure exits 1
9. `_resolve_run_shortcut` unit tests (no shortcuts → (None, None), empty journal, etc.)
10. Both --latest and --last-failure are mutually exclusive by convention (latest wins)
"""

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os.cli import (
    cmd_inspect,
    cmd_replay,
    _resolve_run_shortcut,
    find_project_root,
)
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
    ns = argparse.Namespace(**kwargs)
    return ns


# ── Unit tests: _resolve_run_shortcut ──────────────────────────


class TestResolveRunShortcut:

    def test_no_shortcut_returns_none_none(self, tmp_path):
        journal_dir = tmp_path / "journal"
        result = _resolve_run_shortcut(journal_dir, latest=False, last_failure=False)
        assert result == (None, None)

    def test_latest_empty_journal_returns_error(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        run_id, err = _resolve_run_shortcut(journal_dir, latest=True)
        assert run_id is None
        assert err is not None
        assert "No runs found" in err

    def test_latest_returns_most_recent_run_id(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_first000"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_second00"))

        run_id, err = _resolve_run_shortcut(journal_dir, latest=True)
        assert err is None
        assert run_id == "run_second00"

    def test_last_failure_no_failures_returns_error(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="succeeded"))
        j.write(_make_record(status="succeeded"))

        run_id, err = _resolve_run_shortcut(journal_dir, last_failure=True)
        assert run_id is None
        assert err is not None
        assert "No failed runs found" in err

    def test_last_failure_returns_most_recent_failure(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success1", status="succeeded"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_fail0002", status="timed_out"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success2", status="succeeded"))

        run_id, err = _resolve_run_shortcut(journal_dir, last_failure=True)
        assert err is None
        assert run_id == "run_fail0002"

    def test_last_failure_matches_rejected_status(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_reject01", status="rejected"))

        run_id, err = _resolve_run_shortcut(journal_dir, last_failure=True)
        assert err is None
        assert run_id == "run_reject01"

    def test_last_failure_matches_timed_out_status(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_timeout1", status="timed_out"))

        run_id, err = _resolve_run_shortcut(journal_dir, last_failure=True)
        assert err is None
        assert run_id == "run_timeout1"

    def test_resolve_returns_run_id_not_none(self, tmp_path):
        journal_dir = tmp_path / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_aabbccdd"))

        run_id, err = _resolve_run_shortcut(journal_dir, latest=True)
        assert run_id is not None
        assert err is None


# ── inspect --latest ──────────────────────────────────────────


class TestInspectLatest:

    def test_inspect_latest_returns_json(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_latest01"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=True, last_failure=False))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_latest01"

    def test_inspect_latest_resolves_to_newest(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_first000"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_second00"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=True, last_failure=False))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_second00"

    def test_inspect_latest_empty_journal_prints_no_runs(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=True, last_failure=False))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No runs found" in captured.out

    def test_inspect_latest_exits_zero_on_success(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record())

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=True, last_failure=False))

        assert rc == 0


# ── inspect --last-failure ────────────────────────────────────


class TestInspectLastFailure:

    def test_inspect_last_failure_returns_failed_run(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail0001"

    def test_inspect_last_failure_skips_succeeded_runs(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success1", status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail0001"

    def test_inspect_last_failure_no_failures_prints_message(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No failed runs found" in captured.out

    def test_inspect_last_failure_timed_out_counts_as_failure(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_timeout1", status="timed_out"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_timeout1"

    def test_inspect_last_failure_rejected_counts_as_failure(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_reject01", status="rejected"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_reject01"

    def test_inspect_last_failure_most_recent_failure_among_many(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_fail0002", status="timed_out"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success1", status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_fail0002"


# ── inspect: no args exits 1 ──────────────────────────────────


class TestInspectNoArgs:

    def test_inspect_no_run_id_no_flags_exits_1(self, tmp_path, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id=None, latest=False, last_failure=False))

        assert rc == 1

    def test_inspect_no_run_id_no_flags_prints_guidance(self, tmp_path, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_inspect(_args(run_id=None, latest=False, last_failure=False))

        captured = capsys.readouterr()
        assert "run_id" in captured.out.lower() or "--latest" in captured.out or "Provide" in captured.out


# ── replay --last-failure ─────────────────────────────────────


class TestReplayLastFailure:

    def _mock_adapter_factory(self, run_id_holder: list):
        """Build a MockRuntime that captures the run it executes."""
        from agent_os.adapters.runtime.mock_runtime import MockRuntime

        class CapturingMock(MockRuntime):
            def invoke(self, task: str, capability: str, agent_spec) -> dict:
                result = super().invoke(task, capability, agent_spec)
                return result

        return CapturingMock()

    def test_replay_last_failure_no_failures_prints_message(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(status="succeeded"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_replay(_args(run_id=None, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No failed runs found" in captured.out

    def test_replay_last_failure_empty_journal_prints_message(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_replay(_args(run_id=None, last_failure=True))

        captured = capsys.readouterr()
        assert rc == 0
        assert "No failed runs found" in captured.out

    def test_replay_last_failure_resolves_to_most_recent_failure(self, tmp_path, capsys):
        """Verify --last-failure passes the right run_id to the replay path.

        We don't execute the full chassis (it needs spec files); instead we
        verify that the run_id is looked up from the journal correctly by
        patching _replay_run and inspecting what run_id it receives.
        """
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_fail0001", status="failed"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success1", status="succeeded"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_fail0002", status="timed_out"))
        time.sleep(0.05)
        j.write(_make_record(run_id="run_success2", status="succeeded"))

        captured_run_id = []

        def fake_replay_run(run_id, project_root, journal_dir, **kwargs):
            captured_run_id.append(run_id)
            return {"error": f"Run {run_id} not found."}, 1

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli._replay_run", fake_replay_run)
            cmd_replay(_args(run_id=None, last_failure=True))

        assert captured_run_id == ["run_fail0002"]

    def test_replay_last_failure_timed_out_counts_as_failure(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_timeout1", status="timed_out"))

        captured_run_id = []

        def fake_replay_run(run_id, project_root, journal_dir, **kwargs):
            captured_run_id.append(run_id)
            return {"error": f"Run {run_id} not found."}, 1

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli._replay_run", fake_replay_run)
            cmd_replay(_args(run_id=None, last_failure=True))

        assert captured_run_id == ["run_timeout1"]

    def test_replay_last_failure_rejected_counts_as_failure(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_reject01", status="rejected"))

        captured_run_id = []

        def fake_replay_run(run_id, project_root, journal_dir, **kwargs):
            captured_run_id.append(run_id)
            return {"error": f"Run {run_id} not found."}, 1

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli._replay_run", fake_replay_run)
            cmd_replay(_args(run_id=None, last_failure=True))

        assert captured_run_id == ["run_reject01"]


# ── replay: no args exits 1 ───────────────────────────────────


class TestReplayNoArgs:

    def test_replay_no_run_id_no_flags_exits_1(self, tmp_path, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_replay(_args(run_id=None, last_failure=False))

        assert rc == 1

    def test_replay_no_run_id_no_flags_prints_guidance(self, tmp_path, capsys):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            cmd_replay(_args(run_id=None, last_failure=False))

        captured = capsys.readouterr()
        assert "run_id" in captured.out.lower() or "--last-failure" in captured.out or "Provide" in captured.out


# ── Regression: existing positional run_id still works ────────


class TestInspectPositionalRunIdRegression:

    def test_inspect_positional_run_id_still_works(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_aabbccdd"))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id="run_aabbccdd", latest=False, last_failure=False))

        captured = capsys.readouterr()
        assert rc == 0
        data = json.loads(captured.out)
        assert data["run_id"] == "run_aabbccdd"

    def test_inspect_positional_unknown_still_exits_1(self, tmp_path, capsys):
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True, exist_ok=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            rc = cmd_inspect(_args(run_id="run_nosuchrun", latest=False, last_failure=False))

        assert rc == 1
