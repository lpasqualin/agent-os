"""Phase 2A tests — Sandbox OpenClaw Runtime Adapter.

Proves:
1. clawbot.sandbox.agent.yaml validates and boots via OpenClawRuntime
2. OpenClawRuntime implements the RuntimeAdapter contract
3. Capability mappings are correct (tasks.read→todoist, web.search→tavily)
4. execute() invokes the adapter and returns a normalized result
5. Lifecycle / journal still works through the real adapter path
6. Phase 1 regressions: Chassis without adapter_factory still uses MockRuntime

All OpenClaw subprocess calls are mocked via invoke_fn injection — no live
OpenClaw instance or API keys required for these tests.
"""

import pytest
from pathlib import Path

from agent_os.chassis import Chassis
from agent_os.adapters.runtime.openclaw_runtime import OpenClawRuntime
from agent_os.adapters.interfaces import RuntimeAdapter


# ── Helpers ───────────────────────────────────────────────────

def _project_root() -> Path:
    return Path(__file__).parent.parent.parent


def _registry_path() -> Path:
    return _project_root() / "capabilities" / "registry.yaml"


def _sandbox_spec_path() -> Path:
    return _project_root() / "specs" / "clawbot.sandbox.agent.yaml"


def _prod_spec_path() -> Path:
    return _project_root() / "specs" / "clawbot.agent.yaml"


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def sandbox_root(tmp_path):
    """Minimal sandbox directory tree with a valid config stub."""
    (tmp_path / "config").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "config" / "openclaw.json").write_text(
        '{"meta": {"lastTouchedVersion": "2026.3.12"}}'
    )
    return tmp_path


@pytest.fixture
def mock_invoke():
    """Deterministic invoke_fn that records calls and returns a canned response."""
    calls = []

    def _fn(message: str) -> dict:
        calls.append(message)
        return {
            "status": "ok",
            "reply": f"sandbox response to: {message}",
            "tool": "mock",
        }

    _fn.calls = calls
    return _fn


@pytest.fixture
def runtime(sandbox_root, mock_invoke):
    """OpenClawRuntime with mocked invocation boundary."""
    return OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=mock_invoke)


@pytest.fixture
def openclaw_factory(sandbox_root, mock_invoke):
    """adapter_factory that returns OpenClawRuntime for 'openclaw' target."""
    from agent_os.adapters.runtime.mock_runtime import MockRuntime

    def factory(target: str):
        if target == "openclaw":
            return OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=mock_invoke)
        return MockRuntime()

    return factory


@pytest.fixture
def booted_sandbox(openclaw_factory):
    """Fully booted Chassis with sandbox spec and OpenClawRuntime."""
    chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
    report = chassis.boot(_sandbox_spec_path())
    assert report.success, f"Sandbox boot failed: {report.errors}"
    return chassis


# ── 1. Spec validation ────────────────────────────────────────

class TestSandboxSpecValidation:
    """Sandbox spec passes both validation passes."""

    def test_schema_validation_passes(self):
        from agent_os.validators.schema_validator import validate_schema
        spec, result = validate_schema(_sandbox_spec_path())
        assert result.passed, f"Schema errors: {result.errors}"
        assert spec is not None
        assert spec.id == "clawbot-sandbox"

    def test_registry_validation_passes(self):
        from agent_os.validators.registry_validator import validate_registry
        from agent_os.loaders.yaml_loader import load_agent_spec, load_registry
        spec = load_agent_spec(_sandbox_spec_path())
        registry = load_registry(_registry_path())
        result = validate_registry(spec, registry)
        assert result.passed, f"Registry errors: {result.errors}"

    def test_all_sandbox_capabilities_are_known(self):
        from agent_os.loaders.yaml_loader import load_agent_spec, load_registry
        spec = load_agent_spec(_sandbox_spec_path())
        registry = load_registry(_registry_path())
        registry_ids = registry.ids()
        for cap in spec.capabilities:
            assert cap.id in registry_ids, f"Capability '{cap.id}' not in registry"

    def test_sandbox_has_no_channels(self):
        from agent_os.loaders.yaml_loader import load_agent_spec
        spec = load_agent_spec(_sandbox_spec_path())
        assert spec.channels == [], "Sandbox spec must declare no channels (no Telegram)"

    def test_sandbox_has_no_schedule(self):
        from agent_os.loaders.yaml_loader import load_agent_spec
        spec = load_agent_spec(_sandbox_spec_path())
        assert spec.schedule == [], "Sandbox spec must have no cron schedule"


# ── 2. Boot with OpenClawRuntime ──────────────────────────────

class TestSandboxBoot:
    """Chassis boots sandbox spec with OpenClawRuntime via adapter_factory."""

    def test_boot_succeeds(self, openclaw_factory):
        chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
        report = chassis.boot(_sandbox_spec_path())
        assert report.success, f"Boot errors: {report.errors}"

    def test_agent_id_is_clawbot_sandbox(self, openclaw_factory):
        chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
        report = chassis.boot(_sandbox_spec_path())
        assert report.agent_id == "clawbot-sandbox"

    def test_runtime_is_openclaw(self, openclaw_factory):
        chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
        chassis.boot(_sandbox_spec_path())
        assert isinstance(chassis.runtime, OpenClawRuntime)

    def test_all_adapters_healthy(self, openclaw_factory):
        chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
        report = chassis.boot(_sandbox_spec_path())
        assert report.success
        for name, health in report.adapter_health.items():
            assert health["status"] == "ok", f"{name} unhealthy: {health}"

    def test_all_required_capabilities_mapped(self, openclaw_factory):
        chassis = Chassis(registry_path=_registry_path(), adapter_factory=openclaw_factory)
        report = chassis.boot(_sandbox_spec_path())
        assert report.success
        for cap_id, tool in report.capability_mappings.items():
            assert tool is not None, f"Capability '{cap_id}' unmapped"


# ── 3. Capability mappings ────────────────────────────────────

class TestCapabilityMappings:
    """resolve_capability returns the right OpenClaw skill for each capability."""

    def test_tasks_read_maps_to_todoist(self, runtime):
        assert runtime.resolve_capability("tasks.read") == "todoist"

    def test_web_search_maps_to_tavily(self, runtime):
        assert runtime.resolve_capability("web.search") == "tavily"

    def test_memory_recall_maps_to_openclaw_memory(self, runtime):
        result = runtime.resolve_capability("memory.recall")
        assert result == "openclaw_memory"

    def test_unknown_capability_raises(self, runtime):
        with pytest.raises(ValueError, match="calendar.list"):
            runtime.resolve_capability("calendar.list")

    def test_unsupported_capability_error_names_supported_set(self, runtime):
        with pytest.raises(ValueError, match="tasks.read"):
            runtime.resolve_capability("tasks.write")  # write is not in Phase 2A

    def test_known_capabilities_are_all_mapped(self, runtime):
        for cap in ["tasks.read", "web.search", "memory.recall"]:
            assert runtime.resolve_capability(cap) is not None

    def test_boot_fails_cleanly_with_out_of_scope_capability(
        self, sandbox_root, mock_invoke
    ):
        """Booting a spec that requests an unsupported capability produces a clean
        BootReport error — not an unhandled exception."""
        import yaml, tempfile

        out_of_scope_spec = {
            "id": "bad-agent",
            "name": "Bad Agent",
            "version": "0.0.1",
            "capabilities": [
                {"id": "tasks.read", "policy": "allow", "required": True},
                {"id": "tasks.write", "policy": "allow", "required": True},  # unsupported
            ],
            "runtime": {"target": "openclaw"},
        }
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump(out_of_scope_spec, tmp)
        tmp.close()

        from agent_os.adapters.runtime.mock_runtime import MockRuntime

        def factory(target):
            if target == "openclaw":
                return OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=mock_invoke)
            return MockRuntime()

        chassis = Chassis(registry_path=_registry_path(), adapter_factory=factory)
        report = chassis.boot(tmp.name)

        Path(tmp.name).unlink()

        assert not report.success, "Boot should fail for unsupported capability"
        assert any("tasks.write" in err for err in report.errors), (
            f"Error should name the unsupported capability: {report.errors}"
        )


# ── 4. Execute — invocation and normalized result ─────────────

class TestExecute:
    """execute() calls invoke_fn and stores a normalized result."""

    def test_execute_returns_run_id(self, runtime):
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        run_id = runtime.execute("clawbot-sandbox", "fetch my tasks")
        assert run_id.startswith("run_")
        assert len(run_id) == 12  # "run_" + 8 hex chars

    def test_execute_calls_invoke_fn(self, runtime, mock_invoke):
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        runtime.execute("clawbot-sandbox", "search for python packaging")
        assert "search for python packaging" in mock_invoke.calls

    def test_execute_stores_result(self, runtime, mock_invoke):
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        run_id = runtime.execute("clawbot-sandbox", "list tasks")
        stored = runtime.get_run_result("clawbot-sandbox", run_id)
        assert stored is not None
        assert stored["result"]["status"] == "ok"
        assert "sandbox response to: list tasks" in stored["result"]["reply"]

    def test_execute_tasks_read_invokes_adapter(self, runtime, mock_invoke):
        """tasks.read capability: invoke_fn receives the task message."""
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        run_id = runtime.execute("clawbot-sandbox", "tasks.read: get all tasks")
        stored = runtime.get_run_result("clawbot-sandbox", run_id)
        assert stored is not None
        assert stored["task"] == "tasks.read: get all tasks"

    def test_execute_web_search_invokes_adapter(self, runtime, mock_invoke):
        """web.search capability: invoke_fn receives the task message."""
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        run_id = runtime.execute("clawbot-sandbox", "web.search: agent OS frameworks")
        stored = runtime.get_run_result("clawbot-sandbox", run_id)
        assert stored is not None
        assert stored["task"] == "web.search: agent OS frameworks"

    def test_execute_survives_invoke_error(self, sandbox_root):
        """Adapter never raises even when invoke_fn raises."""
        def bad_invoke(msg):
            raise RuntimeError("simulated OpenClaw failure")

        rt = OpenClawRuntime(sandbox_root=sandbox_root, invoke_fn=bad_invoke)
        rt.deploy({"id": "clawbot-sandbox"})
        rt.start("clawbot-sandbox")

        run_id = rt.execute("clawbot-sandbox", "any task")
        assert run_id.startswith("run_")  # still returns a run_id
        stored = rt.get_run_result("clawbot-sandbox", run_id)
        assert stored["result"]["status"] == "error"

    def test_multiple_runs_are_independent(self, runtime, mock_invoke):
        runtime.deploy({"id": "clawbot-sandbox"})
        runtime.start("clawbot-sandbox")
        run1 = runtime.execute("clawbot-sandbox", "task one")
        run2 = runtime.execute("clawbot-sandbox", "task two")
        assert run1 != run2
        r1 = runtime.get_run_result("clawbot-sandbox", run1)
        r2 = runtime.get_run_result("clawbot-sandbox", run2)
        assert "task one" in r1["result"]["reply"]
        assert "task two" in r2["result"]["reply"]


# ── 5. Lifecycle / journal ────────────────────────────────────

class TestLifecycle:
    """Full execute_task() pipeline works through OpenClawRuntime."""

    def test_execute_task_succeeds(self, booted_sandbox):
        result = booted_sandbox.execute_task("search for agent OS patterns")
        assert result["status"] == "succeeded"

    def test_lifecycle_passes_through_planning(self, booted_sandbox):
        result = booted_sandbox.execute_task("find my tasks")
        states = set()
        for step in result["lifecycle"]:
            states.add(step["from"])
            states.add(step["to"])
        assert "planning" in states, f"'planning' not in lifecycle: {result['lifecycle']}"

    def test_lifecycle_reaches_succeeded(self, booted_sandbox):
        result = booted_sandbox.execute_task("web search: python async patterns")
        states = set()
        for step in result["lifecycle"]:
            states.add(step["to"])
        assert "succeeded" in states

    def test_lifecycle_has_run_id(self, booted_sandbox):
        result = booted_sandbox.execute_task("any task")
        assert "run_id" in result
        assert result["run_id"].startswith("run_")

    def test_invoke_fn_called_during_execute_task(self, booted_sandbox, mock_invoke):
        """The chassis's execute_task() reaches through to OpenClaw invocation."""
        initial_calls = len(mock_invoke.calls)
        booted_sandbox.execute_task("morning briefing")
        assert len(mock_invoke.calls) > initial_calls


# ── 6. Adapter contract ───────────────────────────────────────

class TestAdapterContract:
    """OpenClawRuntime fully implements the RuntimeAdapter ABC."""

    def test_is_runtime_adapter_subclass(self):
        assert issubclass(OpenClawRuntime, RuntimeAdapter)

    def test_implements_all_abstract_methods(self, runtime):
        """Instantiation would fail if any abstract method were missing."""
        assert callable(runtime.deploy)
        assert callable(runtime.start)
        assert callable(runtime.stop)
        assert callable(runtime.status)
        assert callable(runtime.execute)
        assert callable(runtime.resolve_capability)
        assert callable(runtime.health)

    def test_health_returns_ok(self, runtime):
        h = runtime.health()
        assert h["status"] == "ok"
        assert h["runtime"] == "openclaw"
        assert h["mode"] == "sandbox"

    def test_health_reports_config_exists(self, runtime, sandbox_root):
        h = runtime.health()
        assert h["config_exists"] is True

    def test_deploy_returns_agent_id(self, runtime):
        returned = runtime.deploy({"id": "test-agent"})
        assert returned == "test-agent"

    def test_start_returns_true_after_deploy(self, runtime):
        runtime.deploy({"id": "test-agent"})
        assert runtime.start("test-agent") is True

    def test_stop_returns_true_after_start(self, runtime):
        runtime.deploy({"id": "test-agent"})
        runtime.start("test-agent")
        assert runtime.stop("test-agent") is True

    def test_status_reflects_state_transitions(self, runtime):
        runtime.deploy({"id": "test-agent"})
        assert runtime.status("test-agent")["state"] == "deployed"
        runtime.start("test-agent")
        assert runtime.status("test-agent")["state"] == "running"
        runtime.stop("test-agent")
        assert runtime.status("test-agent")["state"] == "stopped"

    def test_status_not_found(self, runtime):
        assert runtime.status("ghost-agent")["status"] == "not_found"


# ── 7. Phase 1 regression guard ───────────────────────────────

class TestPhase1Regression:
    """Chassis without adapter_factory still uses MockRuntime — Phase 1 unchanged."""

    def test_no_factory_uses_mock_runtime(self):
        from agent_os.adapters.runtime.mock_runtime import MockRuntime
        chassis = Chassis(registry_path=_registry_path())
        chassis.boot(_prod_spec_path())
        assert isinstance(chassis.runtime, MockRuntime)

    def test_prod_spec_still_boots_without_factory(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_prod_spec_path())
        assert report.success, f"Prod spec boot regressed: {report.errors}"

    def test_prod_spec_all_capabilities_still_mapped(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_prod_spec_path())
        assert report.success
        for cap_id, tool in report.capability_mappings.items():
            assert tool is not None, f"Phase 1 regression: '{cap_id}' unmapped"

    def test_prod_spec_task_execution_still_succeeds(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_prod_spec_path())
        assert report.success
        result = chassis.execute_task("test_task")
        assert result["status"] == "succeeded"

    def test_prod_spec_lifecycle_still_hits_planning(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_prod_spec_path())
        assert report.success
        result = chassis.execute_task("test_task")
        states = {s for step in result["lifecycle"] for s in (step["from"], step["to"])}
        assert "planning" in states
