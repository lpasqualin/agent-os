"""Phase 2B tests — Runtime Contract Hardening.

Proves:
1. RuntimeExecutionResult shape is validated before the chassis accepts it
2. UnsupportedCapabilityError → 'rejected' status, planning→failed lifecycle
3. RuntimeTimeoutError → 'timed_out' status, executing→failed lifecycle
4. RuntimeInvocationError → 'failed' status, executing→failed lifecycle
5. RuntimeContractError → 'failed' status, executing→failed lifecycle
6. Chassis rejects a result that is not a RuntimeExecutionResult instance
7. RuntimeStatus.FAILED returned by runtime → executing→failed lifecycle
8. Success path: RuntimeStatus.SUCCEEDED → executing→succeeded, output surfaced

All tests use inject_fn or a custom RuntimeAdapter subclass — no subprocess I/O.
"""

import uuid
from datetime import datetime, timezone

import pytest

from agent_os.chassis import Chassis
from agent_os.adapters.interfaces import RuntimeAdapter
from agent_os.contracts.models import RuntimeExecutionResult, RuntimeStatus
from agent_os.contracts.errors import (
    UnsupportedCapabilityError,
    RuntimeInvocationError,
    RuntimeTimeoutError,
    RuntimeContractError,
)


# ── Helpers ───────────────────────────────────────────────────

def _project_root():
    from pathlib import Path
    return Path(__file__).parent.parent.parent


def _registry_path():
    return _project_root() / "capabilities" / "registry.yaml"


def _prod_spec_path():
    return _project_root() / "specs" / "clawbot.agent.yaml"


def _make_result(status: RuntimeStatus, output: str | None = "ok", error: str | None = None) -> RuntimeExecutionResult:
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


# ── Custom runtime stubs ──────────────────────────────────────

class _StubRuntime(RuntimeAdapter):
    """A configurable stub runtime that raises or returns on demand."""

    def __init__(self, execute_fn):
        self._execute_fn = execute_fn
        self._deployed: dict[str, dict] = {}

    def deploy(self, agent_spec: dict, env_binding=None) -> str:
        agent_id = agent_spec.get("id", "unknown")
        self._deployed[agent_id] = {"spec": agent_spec, "state": "deployed"}
        for cap in agent_spec.get("capabilities", []):
            pass  # record nothing — resolve_capability handles it
        return agent_id

    def start(self, agent_id: str) -> bool:
        if agent_id in self._deployed:
            self._deployed[agent_id]["state"] = "running"
            return True
        return False

    def stop(self, agent_id: str) -> bool:
        if agent_id in self._deployed:
            self._deployed[agent_id]["state"] = "stopped"
            return True
        return False

    def status(self, agent_id: str) -> dict:
        if agent_id not in self._deployed:
            return {"status": "not_found"}
        return {"agent_id": agent_id, "state": self._deployed[agent_id]["state"]}

    def execute(self, agent_id: str, capability: str, task: str) -> RuntimeExecutionResult:
        return self._execute_fn(agent_id, capability, task)

    def resolve_capability(self, capability_id: str) -> str | None:
        return f"stub_tool:{capability_id}"

    def health(self) -> dict:
        return {"status": "ok", "runtime": "stub"}


class _RejectingRuntime(_StubRuntime):
    """resolve_capability always raises UnsupportedCapabilityError."""

    def resolve_capability(self, capability_id: str):
        raise UnsupportedCapabilityError(
            f"_RejectingRuntime: '{capability_id}' not supported"
        )


class _BadShapeRuntime(_StubRuntime):
    """execute() returns a plain dict instead of RuntimeExecutionResult."""

    def execute(self, agent_id: str, capability: str, task: str):
        return {"status": "ok", "reply": "not a RuntimeExecutionResult"}  # type: ignore


# ── Fixtures ──────────────────────────────────────────────────

def _booted_chassis(runtime_instance):
    """Boot a chassis with the given runtime, using prod spec."""
    chassis = Chassis(
        registry_path=_registry_path(),
        adapter_factory=lambda target: runtime_instance,
    )
    report = chassis.boot(_prod_spec_path())
    assert report.success, f"Boot failed: {report.errors}"
    return chassis


# ── 1. Success path ───────────────────────────────────────────

class TestSuccessPath:
    """RuntimeStatus.SUCCEEDED → succeeded lifecycle, output surfaced."""

    def test_succeeded_status_in_result(self):
        rt = _StubRuntime(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED, output="done"))
        chassis = _booted_chassis(rt)
        result = chassis.execute_task("do the thing")
        assert result["status"] == "succeeded"

    def test_output_is_surfaced(self):
        rt = _StubRuntime(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED, output="task output"))
        chassis = _booted_chassis(rt)
        result = chassis.execute_task("do the thing")
        assert result["output"] == "task output"

    def test_lifecycle_executing_to_succeeded(self):
        rt = _StubRuntime(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = _booted_chassis(rt)
        result = chassis.execute_task("do the thing")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "succeeded") in transitions

    def test_duration_ms_present(self):
        rt = _StubRuntime(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = _booted_chassis(rt)
        result = chassis.execute_task("do the thing")
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)

    def test_tool_used_present(self):
        rt = _StubRuntime(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = _booted_chassis(rt)
        result = chassis.execute_task("do the thing")
        assert "tool_used" in result
        assert result["tool_used"] is not None


# ── 2. UnsupportedCapabilityError → rejected ─────────────────
#
# Two rejection paths:
#   A. resolve_capability raises before governance (planning→failed, "rejected")
#   B. execute() raises UnsupportedCapabilityError (executing→failed, "rejected")
#
# Path A: resolved at pre-governance check in execute_task().
# We simulate this with a runtime that passes boot (resolve returns a value for
# the first call per capability) then raises on the next call — achieved cleanly
# via a simple counter gated on an instance flag set after boot.
#
# Path B: execute() raises directly.

class TestUnsupportedCapability:
    """UnsupportedCapabilityError paths → 'rejected' status."""

    def _make_reject_on_execute_rt(self):
        """Runtime that resolves caps at boot but raises UnsupportedCapabilityError
        from execute() — tests the executing-time rejection path."""
        def _raise_unsupported(a, c, t):
            raise UnsupportedCapabilityError(f"'{c}' rejected at execute time")
        return _StubRuntime(_raise_unsupported)

    def test_rejected_status_when_execute_raises(self):
        chassis = _booted_chassis(self._make_reject_on_execute_rt())
        result = chassis.execute_task("any task")
        assert result["status"] == "rejected"

    def test_executing_to_failed_when_execute_raises(self):
        chassis = _booted_chassis(self._make_reject_on_execute_rt())
        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "failed") in transitions

    def test_rejected_status_when_resolve_raises_pre_governance(self):
        """resolve_capability raises before governance → planning→failed, rejected."""
        class _RejectAfterBoot(_StubRuntime):
            def __init__(self, execute_fn):
                super().__init__(execute_fn)
                self._booted = False

            def resolve_capability(self, capability_id):
                if not self._booted:
                    return f"tool:{capability_id}"
                raise UnsupportedCapabilityError(f"'{capability_id}' rejected post-boot")

        rt = _RejectAfterBoot(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
        )
        report = chassis.boot(_prod_spec_path())
        assert report.success, f"Boot failed: {report.errors}"

        # Now mark as booted so future resolve_capability calls raise
        rt._booted = True

        result = chassis.execute_task("any task")
        assert result["status"] == "rejected"

    def test_planning_to_failed_pre_governance_rejection(self):
        class _RejectAfterBoot2(_StubRuntime):
            def __init__(self, execute_fn):
                super().__init__(execute_fn)
                self._booted = False

            def resolve_capability(self, capability_id):
                if not self._booted:
                    return f"tool:{capability_id}"
                raise UnsupportedCapabilityError("rejected")

        rt = _RejectAfterBoot2(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
        )
        report = chassis.boot(_prod_spec_path())
        assert report.success
        rt._booted = True

        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("planning", "failed") in transitions

    def test_no_executing_state_on_pre_governance_rejection(self):
        class _RejectAfterBoot3(_StubRuntime):
            def __init__(self, execute_fn):
                super().__init__(execute_fn)
                self._booted = False

            def resolve_capability(self, capability_id):
                if not self._booted:
                    return f"tool:{capability_id}"
                raise UnsupportedCapabilityError("rejected")

        rt = _RejectAfterBoot3(lambda a, c, t: _make_result(RuntimeStatus.SUCCEEDED))
        chassis = Chassis(
            registry_path=_registry_path(),
            adapter_factory=lambda target: rt,
        )
        chassis.boot(_prod_spec_path())
        rt._booted = True

        result = chassis.execute_task("any task")
        all_states = {s for step in result["lifecycle"] for s in (step["from"], step["to"])}
        assert "executing" not in all_states


# ── 3. RuntimeTimeoutError → timed_out ───────────────────────

class TestTimeoutError:
    """RuntimeTimeoutError from execute() → timed_out status."""

    def _timeout_rt(self):
        def _raise(a, c, t):
            raise RuntimeTimeoutError("invocation exceeded 30s")
        return _StubRuntime(_raise)

    def test_timed_out_status(self):
        chassis = _booted_chassis(self._timeout_rt())
        result = chassis.execute_task("any task")
        assert result["status"] == "timed_out"

    def test_executing_to_failed_lifecycle(self):
        chassis = _booted_chassis(self._timeout_rt())
        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "failed") in transitions

    def test_error_message_present(self):
        chassis = _booted_chassis(self._timeout_rt())
        result = chassis.execute_task("any task")
        assert result.get("error") is not None
        assert "exceeded" in result["error"]


# ── 4. RuntimeInvocationError → failed ───────────────────────

class TestInvocationError:
    """RuntimeInvocationError from execute() → failed status."""

    def _invocation_rt(self):
        def _raise(a, c, t):
            raise RuntimeInvocationError("subprocess exited 1")
        return _StubRuntime(_raise)

    def test_failed_status(self):
        chassis = _booted_chassis(self._invocation_rt())
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

    def test_executing_to_failed_lifecycle(self):
        chassis = _booted_chassis(self._invocation_rt())
        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "failed") in transitions

    def test_failure_reason_is_runtime_error(self):
        chassis = _booted_chassis(self._invocation_rt())
        result = chassis.execute_task("any task")
        assert result.get("failure_reason") == "runtime_error"


# ── 5. RuntimeContractError → failed ─────────────────────────

class TestContractError:
    """RuntimeContractError from execute() → failed status."""

    def _contract_rt(self):
        def _raise(a, c, t):
            raise RuntimeContractError("OpenClaw returned non-JSON")
        return _StubRuntime(_raise)

    def test_failed_status(self):
        chassis = _booted_chassis(self._contract_rt())
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

    def test_failure_reason_is_runtime_error(self):
        chassis = _booted_chassis(self._contract_rt())
        result = chassis.execute_task("any task")
        assert result.get("failure_reason") == "runtime_error"


# ── 6. Contract violation (bad return shape) ──────────────────

class TestContractViolation:
    """execute() returning a non-RuntimeExecutionResult → contract_violation."""

    def test_contract_violation_status(self):
        chassis = _booted_chassis(_BadShapeRuntime(lambda a, c, t: None))
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"
        assert result.get("failure_reason") == "contract_violation"

    def test_executing_to_failed_on_violation(self):
        chassis = _booted_chassis(_BadShapeRuntime(lambda a, c, t: None))
        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "failed") in transitions


# ── 7. RuntimeStatus.FAILED returned ─────────────────────────

class TestRuntimeFailedStatus:
    """RuntimeStatus.FAILED in result → executing→failed lifecycle."""

    def _failed_rt(self):
        return _StubRuntime(
            lambda a, c, t: _make_result(RuntimeStatus.FAILED, output=None, error="tool returned error")
        )

    def test_failed_status_in_chassis_result(self):
        chassis = _booted_chassis(self._failed_rt())
        result = chassis.execute_task("any task")
        assert result["status"] == "failed"

    def test_executing_to_failed_lifecycle(self):
        chassis = _booted_chassis(self._failed_rt())
        result = chassis.execute_task("any task")
        transitions = [(s["from"], s["to"]) for s in result["lifecycle"]]
        assert ("executing", "failed") in transitions

    def test_error_surfaced(self):
        chassis = _booted_chassis(self._failed_rt())
        result = chassis.execute_task("any task")
        assert result.get("error") == "tool returned error"


# ── 8. Error hierarchy ────────────────────────────────────────

class TestErrorHierarchy:
    """All runtime errors subclass RuntimeExecutionError."""

    def test_unsupported_is_runtime_error(self):
        from agent_os.contracts.errors import RuntimeExecutionError
        assert issubclass(UnsupportedCapabilityError, RuntimeExecutionError)

    def test_invocation_is_runtime_error(self):
        from agent_os.contracts.errors import RuntimeExecutionError
        assert issubclass(RuntimeInvocationError, RuntimeExecutionError)

    def test_timeout_is_runtime_error(self):
        from agent_os.contracts.errors import RuntimeExecutionError
        assert issubclass(RuntimeTimeoutError, RuntimeExecutionError)

    def test_contract_is_runtime_error(self):
        from agent_os.contracts.errors import RuntimeExecutionError
        assert issubclass(RuntimeContractError, RuntimeExecutionError)


# ── 9. RuntimeExecutionResult model ──────────────────────────

class TestExecutionResultModel:
    """RuntimeExecutionResult validates its fields correctly."""

    def test_valid_result_instantiates(self):
        result = _make_result(RuntimeStatus.SUCCEEDED, output="done")
        assert result.status == RuntimeStatus.SUCCEEDED
        assert result.output == "done"

    def test_run_id_is_string(self):
        result = _make_result(RuntimeStatus.SUCCEEDED)
        assert isinstance(result.run_id, str)

    def test_duration_ms_is_int(self):
        result = _make_result(RuntimeStatus.SUCCEEDED)
        assert isinstance(result.duration_ms, int)

    def test_status_enum_values(self):
        assert RuntimeStatus.SUCCEEDED.value == "succeeded"
        assert RuntimeStatus.FAILED.value == "failed"
        assert RuntimeStatus.REJECTED.value == "rejected"
        assert RuntimeStatus.TIMED_OUT.value == "timed_out"
