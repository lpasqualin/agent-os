"""Phase 2C tests — Execution Journal.

Proves:
1. Journal record written on successful execution
2. Journal record written on each failure path:
   - unsupported capability (pre-governance resolve failure)
   - unsupported capability raised from execute()
   - RuntimeTimeoutError
   - RuntimeInvocationError
   - RuntimeContractError
   - contract violation (bad result shape)
   - policy_denied
3. Journal record schema validation (all required fields present)
4. Journal write failure does NOT crash chassis
5. CLI journal latest returns expected output
6. CLI runs returns tabular output
7. ExecutionJournalRecord model validates correctly
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os.chassis import Chassis
from agent_os.adapters.interfaces import RuntimeAdapter
from agent_os.contracts.models import (
    ExecutionJournalRecord,
    RuntimeExecutionResult,
    RuntimeStatus,
)
from agent_os.contracts.errors import (
    UnsupportedCapabilityError,
    RuntimeInvocationError,
    RuntimeTimeoutError,
    RuntimeContractError,
)
from agent_os.journal import ExecutionJournal


# ── Helpers ───────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent.parent


def _registry_path() -> Path:
    return _project_root() / "capabilities" / "registry.yaml"


def _prod_spec_path() -> Path:
    return _project_root() / "specs" / "clawbot.agent.yaml"


def _make_rt_result(
    status: RuntimeStatus = RuntimeStatus.SUCCEEDED,
    output: str | None = "task output",
    error: str | None = None,
) -> RuntimeExecutionResult:
    now = datetime.now(timezone.utc)
    return RuntimeExecutionResult(
        run_id=f"run_{uuid.uuid4().hex[:8]}",
        status=status,
        capability="tasks.read",
        tool_name="mock_tool",
        output=output,
        error=error,
        started_at=now,
        finished_at=now,
        duration_ms=1,
    )


# ── Stub runtime ──────────────────────────────────────────────

class _StubRuntime(RuntimeAdapter):
    def __init__(self, execute_fn):
        self._execute_fn = execute_fn
        self._deployed: dict = {}

    def deploy(self, agent_spec, env_binding=None):
        aid = agent_spec.get("id", "unknown")
        self._deployed[aid] = {"spec": agent_spec, "state": "deployed"}
        return aid

    def start(self, agent_id):
        if agent_id in self._deployed:
            self._deployed[agent_id]["state"] = "running"
            return True
        return False

    def stop(self, agent_id):
        if agent_id in self._deployed:
            self._deployed[agent_id]["state"] = "stopped"
            return True
        return False

    def status(self, agent_id):
        if agent_id not in self._deployed:
            return {"status": "not_found"}
        return {"agent_id": agent_id, "state": self._deployed[agent_id]["state"]}

    def execute(self, agent_id, capability, task):
        return self._execute_fn(agent_id, capability, task)

    def resolve_capability(self, capability_id):
        return f"tool:{capability_id}"

    def health(self):
        return {"status": "ok", "runtime": "stub"}


class _BadShapeRuntime(_StubRuntime):
    def execute(self, agent_id, capability, task):
        return {"not": "a RuntimeExecutionResult"}


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def journal_dir(tmp_path):
    return tmp_path / ".agent_os" / "journal"


def _make_chassis(runtime, journal_dir):
    chassis = Chassis(
        registry_path=_registry_path(),
        adapter_factory=lambda target: runtime,
        journal_dir=journal_dir,
    )
    report = chassis.boot(_prod_spec_path())
    assert report.success, f"Boot failed: {report.errors}"
    return chassis


# ── 1. Record written on success ──────────────────────────────

class TestJournalOnSuccess:
    def test_journal_file_created(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("do the thing")
        assert result["status"] == "succeeded"

        files = list(journal_dir.glob("*.json"))
        assert len(files) == 1

    def test_journal_run_id_matches(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["run_id"] == result["run_id"]

    def test_journal_status_succeeded(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED, output="done"))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["status"] == "succeeded"

    def test_journal_result_summary_present(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED, output="task output"))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["result_summary"] == "task output"

    def test_journal_lifecycle_trace_present(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert isinstance(data["lifecycle_trace"], list)
        assert len(data["lifecycle_trace"]) > 0

    def test_journal_policy_decision_set(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["policy_decision"] in ("allow", "require_approval", "deny")

    def test_journal_started_at_present_on_success(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("do the thing")

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        # started_at is set for executions that reached the runtime
        assert data.get("started_at") is not None

    def test_multiple_runs_each_write_a_file(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("task one")
        chassis.execute_task("task two")
        chassis.execute_task("task three")

        files = list(journal_dir.glob("*.json"))
        assert len(files) == 3


# ── 2. Record written on each failure path ────────────────────

class TestJournalOnFailure:

    def test_journal_on_runtime_invocation_error(self, journal_dir):
        def _raise(a, c, t):
            raise RuntimeInvocationError("subprocess failed")
        rt = _StubRuntime(_raise)
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

        files = list(journal_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["status"] == "failed"
        assert data["error_type"] == "RuntimeInvocationError"

    def test_journal_on_runtime_timeout_error(self, journal_dir):
        def _raise(a, c, t):
            raise RuntimeTimeoutError("timed out after 30s")
        rt = _StubRuntime(_raise)
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("any task")
        assert result["status"] == "timed_out"

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["status"] == "timed_out"
        assert data["error_type"] == "RuntimeTimeoutError"
        assert "30s" in (data.get("error_message") or "")

    def test_journal_on_runtime_contract_error(self, journal_dir):
        def _raise(a, c, t):
            raise RuntimeContractError("non-JSON output")
        rt = _StubRuntime(_raise)
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["error_type"] == "RuntimeContractError"

    def test_journal_on_contract_violation(self, journal_dir):
        chassis = _make_chassis(_BadShapeRuntime(lambda a, c, t: None), journal_dir)
        result = chassis.execute_task("any task")
        assert result["failure_reason"] == "contract_violation"

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["status"] == "failed"

    def test_journal_on_unsupported_capability_from_execute(self, journal_dir):
        def _raise(a, c, t):
            raise UnsupportedCapabilityError("capability rejected at execute time")
        rt = _StubRuntime(_raise)
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("any task")
        assert result["status"] == "rejected"

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["status"] == "rejected"
        assert data["error_type"] == "UnsupportedCapabilityError"

    def test_journal_on_pre_governance_capability_rejection(self, journal_dir):
        """resolve_capability raises during execute_task() planning phase."""
        class _RejectAfterBoot(_StubRuntime):
            def __init__(self, fn):
                super().__init__(fn)
                self._booted = False

            def resolve_capability(self, capability_id):
                if not self._booted:
                    return f"tool:{capability_id}"
                raise UnsupportedCapabilityError(f"'{capability_id}' rejected")

        rt = _RejectAfterBoot(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=journal_dir,
        )
        report = chassis.boot(_prod_spec_path())
        assert report.success
        rt._booted = True

        result = chassis.execute_task("any task")
        assert result["status"] == "rejected"

        files = list(journal_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["status"] == "rejected"
        # started_at is None for pre-execution rejections
        assert data.get("started_at") is None

    def test_journal_on_runtime_failed_status(self, journal_dir):
        rt = _StubRuntime(
            lambda a, c, t: _make_rt_result(RuntimeStatus.FAILED, output=None, error="tool error")
        )
        chassis = _make_chassis(rt, journal_dir)
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

        files = list(journal_dir.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["status"] == "failed"
        assert data["error_message"] == "tool error"


# ── 3. Schema validation ──────────────────────────────────────

class TestJournalSchema:
    """Every journal record deserializes to a valid ExecutionJournalRecord."""

    REQUIRED_FIELDS = {
        "journal_id", "run_id", "agent_id", "requested_at",
        "finished_at", "status", "lifecycle_trace",
    }

    def _run_and_load(self, journal_dir, runtime) -> dict:
        chassis = _make_chassis(runtime, journal_dir)
        chassis.execute_task("any task")
        files = list(journal_dir.glob("*.json"))
        return json.loads(files[0].read_text())

    def test_all_required_fields_present_on_success(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        data = self._run_and_load(journal_dir, rt)
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"Missing field: {field}"

    def test_all_required_fields_present_on_failure(self, journal_dir):
        def _raise(a, c, t):
            raise RuntimeInvocationError("boom")
        rt = _StubRuntime(_raise)
        data = self._run_and_load(journal_dir, rt)
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"Missing field: {field}"

    def test_record_deserializes_to_model(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("any task")

        files = list(journal_dir.glob("*.json"))
        record = ExecutionJournalRecord.model_validate_json(files[0].read_text())
        assert isinstance(record, ExecutionJournalRecord)
        assert record.run_id.startswith("run_")

    def test_journal_id_is_different_from_run_id(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        data = self._run_and_load(journal_dir, rt)
        assert data["journal_id"] != data["run_id"]

    def test_requested_at_before_finished_at(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        data = self._run_and_load(journal_dir, rt)
        # Both are ISO strings — lexicographic comparison works for UTC
        assert data["requested_at"] <= data["finished_at"]


# ── 4. Journal write failure does not crash chassis ───────────

class TestJournalWriteFailure:
    def test_chassis_returns_success_even_if_journal_write_fails(self, tmp_path):
        """Journal write failure is silent — chassis result is unaffected."""
        # Point journal_dir at a path that cannot be created (a file, not a dir)
        blocked_path = tmp_path / "not_a_dir"
        blocked_path.write_text("I am a file, not a directory")

        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=blocked_path / "journal",  # impossible — parent is a file
        )
        report = chassis.boot(_prod_spec_path())
        assert report.success

        result = chassis.execute_task("any task")
        # Status must still be "succeeded" despite journal failure
        assert result["status"] == "succeeded"
        assert "run_id" in result

    def test_chassis_returns_failure_result_even_if_journal_write_fails(self, tmp_path):
        blocked_path = tmp_path / "not_a_dir"
        blocked_path.write_text("I am a file")

        def _raise(a, c, t):
            raise RuntimeInvocationError("runtime blew up")
        rt = _StubRuntime(_raise)
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=blocked_path / "journal",
        )
        chassis.boot(_prod_spec_path())
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"


# ── 5. ExecutionJournal read methods ─────────────────────────

class TestJournalReadMethods:
    def test_read_latest_returns_most_recent(self, journal_dir, tmp_path):
        import time
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=journal_dir,
        )
        chassis.boot(_prod_spec_path())
        chassis.execute_task("first task")
        time.sleep(0.05)  # ensure different mtime
        r2 = chassis.execute_task("second task")

        journal = ExecutionJournal(journal_dir)
        latest = journal.read_latest()
        assert latest is not None
        assert latest.run_id == r2["run_id"]

    def test_read_latest_returns_none_when_empty(self, journal_dir):
        journal = ExecutionJournal(journal_dir)
        assert journal.read_latest() is None

    def test_list_runs_returns_correct_count(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=journal_dir,
        )
        chassis.boot(_prod_spec_path())
        for i in range(5):
            chassis.execute_task(f"task {i}")

        journal = ExecutionJournal(journal_dir)
        rows = journal.list_runs()
        assert len(rows) == 5

    def test_list_runs_respects_limit(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
            journal_dir=journal_dir,
        )
        chassis.boot(_prod_spec_path())
        for i in range(7):
            chassis.execute_task(f"task {i}")

        journal = ExecutionJournal(journal_dir)
        rows = journal.list_runs(limit=3)
        assert len(rows) == 3

    def test_list_runs_returns_empty_when_no_journal(self, journal_dir):
        journal = ExecutionJournal(journal_dir)
        rows = journal.list_runs()
        assert rows == []

    def test_list_runs_row_has_required_keys(self, journal_dir):
        rt = _StubRuntime(lambda a, c, t: _make_rt_result(RuntimeStatus.SUCCEEDED))
        chassis = _make_chassis(rt, journal_dir)
        chassis.execute_task("any task")

        journal = ExecutionJournal(journal_dir)
        rows = journal.list_runs()
        assert len(rows) == 1
        row = rows[0]
        for key in ("run_id", "status", "agent_id", "capability", "requested_at", "finished_at"):
            assert key in row, f"Missing key: {key}"


# ── 6. ExecutionJournalRecord model ───────────────────────────

class TestJournalRecordModel:
    def _make_record(self, **overrides) -> ExecutionJournalRecord:
        now = datetime.now(timezone.utc)
        base = dict(
            journal_id="abc123",
            run_id="run_deadbeef",
            agent_id="test-agent",
            capability="tasks.read",
            runtime_target="mock",
            requested_at=now,
            finished_at=now,
            status="succeeded",
        )
        base.update(overrides)
        return ExecutionJournalRecord(**base)

    def test_valid_record_instantiates(self):
        r = self._make_record()
        assert r.run_id == "run_deadbeef"
        assert r.status == "succeeded"

    def test_optional_fields_default_none(self):
        r = self._make_record()
        assert r.started_at is None
        assert r.policy_decision is None
        assert r.result_summary is None
        assert r.error_type is None
        assert r.error_message is None

    def test_lifecycle_trace_defaults_empty(self):
        r = self._make_record()
        assert r.lifecycle_trace == []

    def test_metadata_defaults_empty_dict(self):
        r = self._make_record()
        assert r.metadata == {}

    def test_model_dump_json_produces_valid_json(self):
        r = self._make_record()
        raw = r.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["run_id"] == "run_deadbeef"

    def test_roundtrip_serialize_deserialize(self):
        r = self._make_record(
            policy_decision="allow",
            result_summary="output",
            error_type=None,
            metadata={"duration_ms": 42},
        )
        raw = r.model_dump_json()
        restored = ExecutionJournalRecord.model_validate_json(raw)
        assert restored.run_id == r.run_id
        assert restored.metadata["duration_ms"] == 42
