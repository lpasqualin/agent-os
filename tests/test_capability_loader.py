"""Tests for agent_os.capabilities.loader.

Covers: registry loading, agent loading, YAML error handling,
missing fields, deterministic ordering, field mapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.capabilities.loader import load_agent, load_registry
from agent_os.capabilities.models import AgentCapabilityGrant, Capability

_FIXTURES = Path(__file__).parent / "fixtures"
_CAP_FIX  = _FIXTURES / "capabilities"
_AGT_FIX  = _FIXTURES / "agents"


# ── Registry loading ──────────────────────────────────────────

class TestLoadRegistry:

    def test_load_valid_registry_returns_no_errors(self):
        registry, errors = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert not errors
        assert registry is not None

    def test_load_valid_registry_has_correct_count(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        assert len(registry.capabilities) == 5

    def test_load_valid_registry_source_file_is_set(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        assert "valid_registry.yaml" in registry.source_file

    def test_load_registry_preserves_source_order(self):
        """Capabilities must be returned in YAML source order (deterministic)."""
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        ids = [c.id for c in registry.capabilities]
        assert ids == ["web.search", "tasks.read", "tasks.write", "email.send", "data.delete"]

    def test_load_registry_maps_all_fields(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        web = next(c for c in registry.capabilities if c.id == "web.search")
        assert web.action_class == "billable_read"
        assert web.idempotent is True
        assert web.compensable == "na"
        assert web.data_sensitivity == "none"
        assert web.justification_required is False

    def test_load_registry_compensable_bool_true(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        cap = next(c for c in registry.capabilities if c.id == "tasks.write")
        assert cap.compensable is True

    def test_load_registry_compensable_bool_false(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        cap = next(c for c in registry.capabilities if c.id == "email.send")
        assert cap.compensable is False

    def test_load_registry_compensable_na_string(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        cap = next(c for c in registry.capabilities if c.id == "web.search")
        assert cap.compensable == "na"

    def test_load_registry_missing_file_returns_error(self, tmp_path):
        registry, errors = load_registry(tmp_path / "nonexistent.yaml")
        assert registry is None
        assert any(e.code == "file_read_error" for e in errors)

    def test_load_registry_invalid_yaml_returns_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(": invalid: [yaml: }{")
        registry, errors = load_registry(bad)
        assert registry is None
        assert any(e.code == "invalid_yaml" for e in errors)

    def test_load_registry_missing_capabilities_key(self, tmp_path):
        f = tmp_path / "nocaps.yaml"
        f.write_text("name: test\n")
        registry, errors = load_registry(f)
        assert registry is None
        assert any(e.code == "missing_required_field" for e in errors)

    def test_load_registry_capability_missing_id(self, tmp_path):
        f = tmp_path / "noid.yaml"
        f.write_text(
            "capabilities:\n"
            "  - action_class: pure_read\n"
            "    idempotent: true\n"
            "    compensable: na\n"
            "    data_sensitivity: none\n"
            "    justification_required: false\n"
        )
        registry, errors = load_registry(f)
        assert any(e.code == "missing_required_field" for e in errors)

    def test_load_registry_partial_parse_on_one_bad_entry(self, tmp_path):
        """Registry returns partial results when only one entry is malformed."""
        f = tmp_path / "partial.yaml"
        f.write_text(
            "capabilities:\n"
            "  - id: web.search\n"
            "    action_class: billable_read\n"
            "    idempotent: true\n"
            "    compensable: na\n"
            "    data_sensitivity: none\n"
            "    justification_required: false\n"
            "  - id: bad_entry_missing_fields\n"
        )
        registry, errors = load_registry(f)
        assert registry is not None
        assert len(registry.capabilities) == 1
        assert registry.capabilities[0].id == "web.search"
        assert errors  # has error for bad entry

    def test_load_registry_returns_capability_instances(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        for cap in registry.capabilities:
            assert isinstance(cap, Capability)


# ── Agent loading ─────────────────────────────────────────────

class TestLoadAgent:

    def test_load_valid_agent_returns_no_errors(self):
        agent, errors = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert not errors
        assert agent is not None

    def test_load_valid_agent_maps_agent_id(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        assert agent.spec.agent_id == "test-agent"

    def test_load_valid_agent_maps_name(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        assert agent.spec.name == "Test Agent"

    def test_load_valid_agent_maps_version(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        assert agent.spec.version == "1.0.0"

    def test_load_valid_agent_capability_count(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        assert len(agent.spec.capabilities) == 4

    def test_load_valid_agent_preserves_source_order(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        ids = [g.id for g in agent.spec.capabilities]
        assert ids == ["web.search", "tasks.read", "tasks.write", "data.delete"]

    def test_load_valid_agent_no_policy_override_is_none(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        web = next(g for g in agent.spec.capabilities if g.id == "web.search")
        assert web.policy_override is None

    def test_load_valid_agent_policy_override_is_set(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        tw = next(g for g in agent.spec.capabilities if g.id == "tasks.write")
        assert tw.policy_override == "confirm"

    def test_load_agent_missing_file_returns_error(self, tmp_path):
        agent, errors = load_agent(tmp_path / "no.yaml")
        assert agent is None
        assert any(e.code == "file_read_error" for e in errors)

    def test_load_agent_invalid_yaml_returns_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(": }{")
        agent, errors = load_agent(bad)
        assert agent is None
        assert any(e.code == "invalid_yaml" for e in errors)

    def test_load_agent_missing_id_field(self, tmp_path):
        f = tmp_path / "noid.yaml"
        f.write_text("name: Test\nversion: 1.0.0\ncapabilities: []\n")
        agent, errors = load_agent(f)
        assert agent is None
        assert any(e.code == "missing_required_field" for e in errors)

    def test_load_agent_missing_name_field(self, tmp_path):
        f = tmp_path / "noname.yaml"
        f.write_text("id: test\nversion: 1.0.0\ncapabilities: []\n")
        agent, errors = load_agent(f)
        assert agent is None
        assert any(e.code == "missing_required_field" for e in errors)

    def test_load_agent_missing_version_field(self, tmp_path):
        f = tmp_path / "nover.yaml"
        f.write_text("id: test\nname: Test\ncapabilities: []\n")
        agent, errors = load_agent(f)
        assert agent is None
        assert any(e.code == "missing_required_field" for e in errors)

    def test_load_agent_no_capabilities_is_ok(self, tmp_path):
        """capabilities: [] is valid at the loader level (validator may warn)."""
        f = tmp_path / "nocaps.yaml"
        f.write_text("id: test\nname: Test\nversion: 1.0.0\ncapabilities: []\n")
        agent, errors = load_agent(f)
        assert agent is not None
        assert agent.spec.capabilities == []

    def test_load_agent_source_file_is_set(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        assert "valid_agent.yaml" in agent.source_file

    def test_load_agent_returns_grant_instances(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        for g in agent.spec.capabilities:
            assert isinstance(g, AgentCapabilityGrant)


# ── Error structure ───────────────────────────────────────────

class TestValidationErrorStructure:

    def test_error_has_code(self, tmp_path):
        _, errors = load_registry(tmp_path / "missing.yaml")
        assert errors[0].code

    def test_error_has_message(self, tmp_path):
        _, errors = load_registry(tmp_path / "missing.yaml")
        assert errors[0].message

    def test_error_has_severity_error(self, tmp_path):
        _, errors = load_registry(tmp_path / "missing.yaml")
        assert errors[0].severity == "error"

    def test_error_str_includes_message(self, tmp_path):
        _, errors = load_registry(tmp_path / "missing.yaml")
        assert errors[0].message in str(errors[0])
