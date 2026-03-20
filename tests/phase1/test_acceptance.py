"""Phase 1 acceptance tests — the three that matter first.

Test 1: Valid agent spec boots successfully
Test 2: Unknown capability fails fast
Test 3: Policy override too permissive fails

Run with: pytest tests/phase1/ -v
"""

import pytest
import yaml
import tempfile
from pathlib import Path

from agent_os.chassis import Chassis
from agent_os.loaders.yaml_loader import load_agent_spec, load_registry
from agent_os.validators.schema_validator import validate_schema
from agent_os.validators.registry_validator import validate_registry


def _project_root() -> Path:
    """Find project root from test file location."""
    return Path(__file__).parent.parent.parent


def _registry_path() -> Path:
    return _project_root() / "capabilities" / "registry.yaml"


def _spec_path() -> Path:
    return _project_root() / "specs" / "clawbot.agent.yaml"


def _write_temp_spec(spec_dict: dict) -> Path:
    """Write a spec dict to a temp YAML file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(spec_dict, tmp, default_flow_style=False)
    tmp.close()
    return Path(tmp.name)


# ── Test 1: Valid spec boots ──────────────────────────────────

class TestValidBoot:
    """Test that ClawBot's real spec passes all validation and boots."""

    def test_schema_validation_passes(self):
        spec, result = validate_schema(_spec_path())
        assert result.passed, f"Schema validation failed: {result.errors}"
        assert spec is not None
        assert spec.id == "clawbot"

    def test_registry_validation_passes(self):
        spec = load_agent_spec(_spec_path())
        registry = load_registry(_registry_path())
        result = validate_registry(spec, registry)
        assert result.passed, f"Registry validation failed: {result.errors}"

    def test_full_boot_succeeds(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_spec_path())
        assert report.success, f"Boot failed: {report.errors}"
        assert report.agent_id == "clawbot"

    def test_all_adapters_healthy(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_spec_path())
        assert report.success
        for name, health in report.adapter_health.items():
            assert health["status"] == "ok", f"{name} adapter unhealthy: {health}"

    def test_all_capabilities_mapped(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_spec_path())
        assert report.success
        for cap_id, tool in report.capability_mappings.items():
            assert tool is not None, f"Capability '{cap_id}' is unmapped"

    def test_mock_task_execution(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_spec_path())
        assert report.success

        result = chassis.execute_task("test_task")
        assert result["status"] == "succeeded"

    def test_lifecycle_passes_through_planning(self):
        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(_spec_path())
        assert report.success

        result = chassis.execute_task("test_task")
        states = set()
        for step in result["lifecycle"]:
            states.add(step["from"])
            states.add(step["to"])
        assert "planning" in states, f"Lifecycle never reached 'planning'. States: {states}"


# ── Test 2: Unknown capability fails fast ─────────────────────

class TestUnknownCapability:
    """Test that specs with unknown capabilities are rejected."""

    def test_unknown_capability_rejected(self):
        spec = load_agent_spec(_spec_path())
        registry = load_registry(_registry_path())

        # Inject a fake capability
        from agent_os.contracts.models import CapabilityRef
        spec.capabilities.append(CapabilityRef(id="unicorn.fly", policy=None, required=False))

        result = validate_registry(spec, registry)
        assert not result.passed, "Should have failed with unknown capability"
        assert any("unicorn.fly" in err for err in result.errors), \
            f"Error should mention 'unicorn.fly': {result.errors}"

    def test_unknown_capability_fails_boot(self):
        # Load real spec, modify it, write to temp
        with open(_spec_path()) as f:
            raw = yaml.safe_load(f)
        raw["capabilities"].append({"id": "unicorn.fly", "policy": "allow"})
        tmp_path = _write_temp_spec(raw)

        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(tmp_path)
        assert not report.success, "Boot should fail with unknown capability"

        tmp_path.unlink()


# ── Test 3: Policy override too permissive fails ──────────────

class TestPolicyPermissiveness:
    """Test that more-permissive-than-default policy overrides are rejected."""

    def test_permissive_override_rejected(self):
        """email.send is irreversible_mutation (default: confirm).
        Setting it to 'allow' is more permissive and must be rejected."""
        with open(_spec_path()) as f:
            raw = yaml.safe_load(f)

        # Override email.send to 'allow' (too permissive)
        for cap in raw["capabilities"]:
            if cap["id"] == "email.send":
                cap["policy"] = "allow"
                break

        tmp_path = _write_temp_spec(raw)

        spec = load_agent_spec(tmp_path)
        registry = load_registry(_registry_path())
        result = validate_registry(spec, registry)

        assert not result.passed, "Should reject permissive override"
        assert any("email.send" in err and "permissive" in err.lower() for err in result.errors), \
            f"Error should explain email.send permissive override: {result.errors}"

        tmp_path.unlink()

    def test_stricter_override_accepted(self):
        """tasks.write is external_mutation (default: confirm).
        Setting it to 'deny' is stricter and must be accepted."""
        with open(_spec_path()) as f:
            raw = yaml.safe_load(f)

        for cap in raw["capabilities"]:
            if cap["id"] == "tasks.write":
                cap["policy"] = "deny"
                break

        tmp_path = _write_temp_spec(raw)

        spec = load_agent_spec(tmp_path)
        registry = load_registry(_registry_path())
        result = validate_registry(spec, registry)

        assert result.passed, f"Stricter override should be accepted: {result.errors}"

        tmp_path.unlink()

    def test_permissive_override_fails_boot(self):
        with open(_spec_path()) as f:
            raw = yaml.safe_load(f)

        for cap in raw["capabilities"]:
            if cap["id"] == "email.send":
                cap["policy"] = "allow"
                break

        tmp_path = _write_temp_spec(raw)

        chassis = Chassis(registry_path=_registry_path())
        report = chassis.boot(tmp_path)
        assert not report.success, "Boot should fail with permissive override"

        tmp_path.unlink()
