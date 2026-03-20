"""Phase 3C tests — governed replay command.

Proves:
1. Replay of valid run creates a NEW run_id (not the original)
2. Replay writes a new journal entry
3. New journal entry includes replay_of_run_id and trigger="operator_replay"
4. Original journal record is NOT modified
5. Replay executes through chassis (invoke_fn is called — not stubbed)
6. Replay of unknown run_id: clean error, exit code 1
7. Replay of non-replayable run (missing context): structured error, no crash
8. No unhandled exceptions in any path
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os.cli import _replay_run, _find_spec_by_agent_id, _enrich_replay_record
from agent_os.adapters.runtime.openclaw_runtime import OpenClawRuntime
from agent_os.adapters.runtime.mock_runtime import MockRuntime
from agent_os.contracts.models import ExecutionJournalRecord
from agent_os.journal import ExecutionJournal


# ── Helpers ───────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent.parent


def _registry_path() -> Path:
    return _project_root() / "capabilities" / "registry.yaml"


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
        lifecycle_trace=[
            {"from": "planning", "to": "executing", "reason": "policy_allowed"},
            {"from": "executing", "to": "succeeded", "reason": "task_complete"},
        ],
    )
    base.update(overrides)
    return ExecutionJournalRecord(**base)


@pytest.fixture
def sandbox_root(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "config" / "openclaw.json").write_text(
        '{"meta": {"lastTouchedVersion": "2026.3.12"}}'
    )
    return tmp_path


@pytest.fixture
def mock_invoke():
    calls = []

    def _fn(message: str) -> dict:
        calls.append(message)
        return {"status": "ok", "reply": f"replay result for: {message}"}

    _fn.calls = calls
    return _fn


@pytest.fixture
def journal_dir(tmp_path):
    d = tmp_path / "journal"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def openclaw_factory(sandbox_root, mock_invoke):
    def factory(target: str):
        if target == "openclaw":
            return OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=mock_invoke)
        return MockRuntime()
    return factory


# ── 1. Replay of valid run ────────────────────────────────────

class TestReplayValidRun:
    """Replay a real journal entry → new run with linkage."""

    def test_replay_creates_new_run_id(self, journal_dir, openclaw_factory):
        original_id = "run_orig0001"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        new_run_id = result.get("_new_run_id")
        assert new_run_id is not None
        assert new_run_id != original_id
        assert new_run_id.startswith("run_")

    def test_replay_writes_new_journal_entry(self, journal_dir, openclaw_factory):
        original_id = "run_orig0002"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        files = list(journal_dir.glob("*.json"))
        assert len(files) == 2, f"Expected 2 journal files, got {len(files)}"

    def test_replay_new_entry_has_replay_of_run_id(self, journal_dir, openclaw_factory):
        original_id = "run_orig0003"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        new_run_id = result["_new_run_id"]
        new_record_path = journal_dir / f"{new_run_id}.json"
        assert new_record_path.exists()
        data = json.loads(new_record_path.read_text())
        assert data["metadata"].get("replay_of_run_id") == original_id

    def test_replay_new_entry_has_trigger_operator_replay(self, journal_dir, openclaw_factory):
        original_id = "run_orig0004"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        new_run_id = result["_new_run_id"]
        data = json.loads((journal_dir / f"{new_run_id}.json").read_text())
        assert data["metadata"].get("trigger") == "operator_replay"

    def test_replay_original_record_unchanged(self, journal_dir, openclaw_factory):
        original_id = "run_orig0005"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        original_text = (journal_dir / f"{original_id}.json").read_text()

        _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert (journal_dir / f"{original_id}.json").read_text() == original_text

    def test_replay_executes_through_chassis(self, journal_dir, openclaw_factory, mock_invoke):
        """invoke_fn is called — proves chassis → runtime path was taken."""
        original_id = "run_orig0006"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        calls_before = len(mock_invoke.calls)
        _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert len(mock_invoke.calls) > calls_before, (
            "invoke_fn was not called — chassis path was bypassed"
        )

    def test_replay_result_has_status(self, journal_dir, openclaw_factory):
        original_id = "run_orig0007"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert result.get("status") in (
            "succeeded", "failed", "rejected", "timed_out", "canceled"
        )

    def test_replay_result_has_lifecycle(self, journal_dir, openclaw_factory):
        original_id = "run_orig0008"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert isinstance(result.get("lifecycle"), list)
        assert len(result["lifecycle"]) > 0

    def test_replay_result_lifecycle_includes_planning(self, journal_dir, openclaw_factory):
        original_id = "run_orig0009"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=original_id))

        result, rc = _replay_run(
            run_id=original_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        states = {s for step in result["lifecycle"] for s in (step["from"], step["to"])}
        assert "planning" in states


# ── 2. Replay of unknown run_id ───────────────────────────────

class TestReplayUnknownRun:
    """Unknown run_id → clean error, exit code 1."""

    def test_unknown_run_id_returns_exit_code_1(self, journal_dir, openclaw_factory):
        result, rc = _replay_run(
            run_id="run_doesnotexist",
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )
        assert rc == 1

    def test_unknown_run_id_error_message_contains_run_id(self, journal_dir, openclaw_factory):
        result, rc = _replay_run(
            run_id="run_doesnotexist",
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )
        assert "run_doesnotexist" in result.get("error", "")

    def test_unknown_run_id_no_new_journal_entry(self, journal_dir, openclaw_factory):
        _replay_run(
            run_id="run_doesnotexist",
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )
        assert list(journal_dir.glob("*.json")) == []

    def test_unknown_run_id_does_not_raise(self, journal_dir, openclaw_factory):
        try:
            _replay_run(
                run_id="run_doesnotexist",
                project_root=_project_root(),
                journal_dir=journal_dir,
                adapter_factory=openclaw_factory,
            )
        except Exception as exc:
            pytest.fail(f"_replay_run raised: {type(exc).__name__}: {exc}")


# ── 3. Replay of non-replayable run ───────────────────────────

class TestReplayNonReplayableRun:
    """Missing required fields → structured error, no crash."""

    def test_missing_capability_is_not_replayable(self, journal_dir, openclaw_factory):
        run_id = "run_nocap001"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id, capability=None))

        result, rc = _replay_run(
            run_id=run_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert "not replayable" in result.get("error", "").lower()

    def test_missing_runtime_target_is_not_replayable(self, journal_dir, openclaw_factory):
        run_id = "run_nort0001"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id, runtime_target=None))

        result, rc = _replay_run(
            run_id=run_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert "not replayable" in result.get("error", "").lower()

    def test_missing_agent_id_is_not_replayable(self, journal_dir, openclaw_factory):
        """agent_id is required to find the spec."""
        run_id = "run_noaid001"
        record = _make_record(run_id=run_id)
        # Write record then manually corrupt agent_id in the file
        j = ExecutionJournal(journal_dir)
        j.write(record)
        path = journal_dir / f"{run_id}.json"
        data = json.loads(path.read_text())
        data["agent_id"] = ""
        path.write_text(json.dumps(data))

        result, rc = _replay_run(
            run_id=run_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert "not replayable" in result.get("error", "").lower()

    def test_unknown_agent_id_is_not_replayable(self, journal_dir, openclaw_factory):
        """agent_id that has no matching spec → not replayable."""
        run_id = "run_badagt01"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id, agent_id="no-such-agent"))

        result, rc = _replay_run(
            run_id=run_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        assert rc == 0
        assert "not replayable" in result.get("error", "").lower()

    def test_non_replayable_does_not_raise(self, journal_dir, openclaw_factory):
        run_id = "run_nocrash1"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id, capability=None))

        try:
            _replay_run(
                run_id=run_id,
                project_root=_project_root(),
                journal_dir=journal_dir,
                adapter_factory=openclaw_factory,
            )
        except Exception as exc:
            pytest.fail(f"_replay_run raised on non-replayable run: {type(exc).__name__}: {exc}")

    def test_non_replayable_writes_no_new_journal_entry(self, journal_dir, openclaw_factory):
        run_id = "run_noentry1"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id, capability=None))

        _replay_run(
            run_id=run_id,
            project_root=_project_root(),
            journal_dir=journal_dir,
            adapter_factory=openclaw_factory,
        )

        # Only original should exist
        files = list(journal_dir.glob("*.json"))
        assert len(files) == 1
        assert files[0].name == f"{run_id}.json"


# ── 4. No unhandled exceptions in any path ────────────────────

class TestNoUnhandledExceptions:
    """_replay_run never raises — all errors returned as structured dicts."""

    def test_runtime_error_in_invoke_fn_is_caught(self, journal_dir):
        """invoke_fn raising RuntimeError → structured result, no unhandled exception."""
        def bad_invoke(msg):
            raise RuntimeError("simulated invocation failure")

        bad_factory = lambda target: OpenClawRuntime(
            sandbox_root=Path("/tmp/nonexistent-sandbox"),
            invoke_fn=bad_invoke,
        )

        run_id = "run_rterror1"
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id=run_id))

        try:
            result, rc = _replay_run(
                run_id=run_id,
                project_root=_project_root(),
                journal_dir=journal_dir,
                adapter_factory=bad_factory,
            )
        except Exception as exc:
            pytest.fail(f"_replay_run propagated exception: {type(exc).__name__}: {exc}")

        # Must return a structured result (either success path or failure path)
        assert isinstance(result, dict)
        assert isinstance(rc, int)

    def test_corrupt_journal_file_does_not_raise(self, journal_dir, openclaw_factory):
        run_id = "run_corrupt1"
        path = journal_dir / f"{run_id}.json"
        path.write_text("this is not valid json {{{{")

        try:
            result, rc = _replay_run(
                run_id=run_id,
                project_root=_project_root(),
                journal_dir=journal_dir,
                adapter_factory=openclaw_factory,
            )
        except Exception as exc:
            pytest.fail(f"_replay_run raised on corrupt file: {type(exc).__name__}: {exc}")

        assert rc == 1  # treated as "not found"


# ── 5. Helper unit tests ──────────────────────────────────────

class TestHelpers:
    """Unit tests for _find_spec_by_agent_id and _enrich_replay_record."""

    def test_find_spec_clawbot_sandbox(self):
        path = _find_spec_by_agent_id(_project_root(), "clawbot-sandbox")
        assert path is not None
        assert path.name == "clawbot.sandbox.agent.yaml"

    def test_find_spec_clawbot(self):
        path = _find_spec_by_agent_id(_project_root(), "clawbot")
        assert path is not None

    def test_find_spec_unknown_agent_returns_none(self):
        path = _find_spec_by_agent_id(_project_root(), "no-such-agent-xyz")
        assert path is None

    def test_enrich_adds_replay_of_run_id(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        run_file = journal_dir / "run_new00001.json"
        run_file.write_text(json.dumps({"metadata": {}}))

        _enrich_replay_record(journal_dir, "run_new00001", "run_original1")

        data = json.loads(run_file.read_text())
        assert data["metadata"]["replay_of_run_id"] == "run_original1"

    def test_enrich_adds_trigger(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        run_file = journal_dir / "run_new00002.json"
        run_file.write_text(json.dumps({"metadata": {}}))

        _enrich_replay_record(journal_dir, "run_new00002", "run_original2")

        data = json.loads(run_file.read_text())
        assert data["metadata"]["trigger"] == "operator_replay"

    def test_enrich_does_not_raise_on_missing_file(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        try:
            _enrich_replay_record(journal_dir, "run_nonexistent", "run_original")
        except Exception as exc:
            pytest.fail(f"_enrich_replay_record raised on missing file: {exc}")

    def test_enrich_preserves_existing_metadata(self, tmp_path):
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        run_file = journal_dir / "run_new00003.json"
        run_file.write_text(json.dumps({"metadata": {"duration_ms": 42}}))

        _enrich_replay_record(journal_dir, "run_new00003", "run_original3")

        data = json.loads(run_file.read_text())
        assert data["metadata"]["duration_ms"] == 42
        assert data["metadata"]["replay_of_run_id"] == "run_original3"


# ── 6. CLI cmd_replay integration ────────────────────────────

class TestCmdReplayIntegration:
    """cmd_replay prints correct output and returns correct exit codes."""

    def test_cmd_replay_unknown_run_exits_1(self, tmp_path, capsys):
        from agent_os.cli import cmd_replay
        import argparse

        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            args = argparse.Namespace(run_id="run_nosuchrun")
            rc = cmd_replay(args)

        assert rc == 1
        captured = capsys.readouterr()
        assert "run_nosuchrun" in captured.out
        assert "not found" in captured.out.lower()

    def test_cmd_replay_prints_original_run_id(self, tmp_path, capsys, sandbox_root, mock_invoke):
        from agent_os.cli import cmd_replay
        import argparse

        # Use real project root for specs/registry, tmp journal dir
        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True)
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_clicheck1"))

        def factory(target):
            if target == "openclaw":
                return OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=mock_invoke)
            return MockRuntime()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            mp.setattr("agent_os.cli._default_adapter_factory", factory)
            # Also patch _replay_run to use real project root for specs
            import agent_os.cli as cli_mod
            original_replay_run = cli_mod._replay_run

            def patched_replay_run(run_id, project_root, journal_dir, adapter_factory=None, registry_path=None):
                return original_replay_run(
                    run_id=run_id,
                    project_root=_project_root(),  # use real root for specs
                    journal_dir=journal_dir,
                    adapter_factory=factory,
                    registry_path=_registry_path(),
                )
            mp.setattr("agent_os.cli._replay_run", patched_replay_run)

            args = argparse.Namespace(run_id="run_clicheck1")
            rc = cmd_replay(args)

        captured = capsys.readouterr()
        assert "run_clicheck1" in captured.out

    def test_cmd_replay_non_replayable_exits_0(self, tmp_path, capsys):
        from agent_os.cli import cmd_replay
        import argparse

        journal_dir = tmp_path / ".agent_os" / "journal"
        journal_dir.mkdir(parents=True)
        j = ExecutionJournal(journal_dir)
        j.write(_make_record(run_id="run_badreply", capability=None))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("agent_os.cli.find_project_root", lambda: tmp_path)
            import agent_os.cli as cli_mod
            original_replay_run = cli_mod._replay_run

            def patched_replay_run(run_id, project_root, journal_dir, adapter_factory=None, registry_path=None):
                return original_replay_run(
                    run_id=run_id,
                    project_root=_project_root(),
                    journal_dir=journal_dir,
                    adapter_factory=_default_adapter_factory,
                    registry_path=_registry_path(),
                )
            mp.setattr("agent_os.cli._replay_run", patched_replay_run)

            args = argparse.Namespace(run_id="run_badreply")
            rc = cmd_replay(args)

        assert rc == 0
        captured = capsys.readouterr()
        assert "not replayable" in captured.out.lower()


def _default_adapter_factory(target):
    return MockRuntime()
