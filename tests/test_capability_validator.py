"""Tests for agent_os.capabilities.validator.

Covers: registry validation, agent validation, stricter-only policy rule,
governance seam (justification_required, compensable, data_sensitivity),
missing capability references, duplicate ids, error message golden tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.capabilities.loader import load_agent, load_registry
from agent_os.capabilities.models import (
    AgentCapabilityGrant,
    AgentSpec,
    Capability,
    LoadedAgent,
    LoadedRegistry,
)
from agent_os.capabilities.validator import validate_agent, validate_registry

_FIXTURES = Path(__file__).parent / "fixtures"
_CAP_FIX  = _FIXTURES / "capabilities"
_AGT_FIX  = _FIXTURES / "agents"


# ── Helpers ───────────────────────────────────────────────────

def _make_cap(**kwargs) -> Capability:
    defaults = dict(
        id="web.search",
        action_class="billable_read",
        idempotent=True,
        compensable="na",
        data_sensitivity="none",
        justification_required=False,
    )
    defaults.update(kwargs)
    return Capability(**defaults)


def _make_registry(*caps: Capability, src: str = "test.yaml") -> LoadedRegistry:
    return LoadedRegistry(capabilities=list(caps), source_file=src)


def _make_agent(*grants: AgentCapabilityGrant, src: str = "agent.yaml") -> LoadedAgent:
    spec = AgentSpec(
        agent_id="test-agent",
        name="Test Agent",
        version="1.0.0",
        capabilities=list(grants),
    )
    return LoadedAgent(spec=spec, source_file=src)


def _grant(cap_id: str, policy: str | None = None) -> AgentCapabilityGrant:
    return AgentCapabilityGrant(id=cap_id, policy_override=policy)


# ── Registry validation ───────────────────────────────────────

class TestValidateRegistry:

    def test_valid_registry_has_no_errors(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        assert errors == []

    def test_duplicate_id_produces_error(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_duplicate_ids.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        codes = [e.code for e in errors]
        assert "duplicate_capability_id" in codes

    def test_duplicate_id_error_message_golden(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_duplicate_ids.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        dup = next(e for e in errors if e.code == "duplicate_capability_id")
        assert dup.message == "duplicate capability id: tasks.write"

    def test_bad_id_format_produces_error(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_bad_id_format.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        codes = [e.code for e in errors]
        assert "invalid_capability_id_format" in codes

    def test_bad_id_format_error_message_golden(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_bad_id_format.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        fmt_errors = [e for e in errors if e.code == "invalid_capability_id_format"]
        messages = {e.message for e in fmt_errors}
        assert "invalid capability id format: Gmail.Send" in messages

    def test_two_bad_ids_both_reported(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_bad_id_format.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        fmt_errors = [e for e in errors if e.code == "invalid_capability_id_format"]
        assert len(fmt_errors) == 2

    def test_valid_id_formats_pass(self):
        for cap_id in ("web.search", "tasks.read", "data.delete", "email.send"):
            cap = _make_cap(id=cap_id)
            errors = validate_registry(_make_registry(cap))
            id_errors = [e for e in errors if e.code == "invalid_capability_id_format"]
            assert id_errors == [], f"Unexpected error for id={cap_id!r}"

    def test_invalid_id_formats_fail(self):
        for cap_id in ("Gmail.Send", "webSearch", "web-search", "web", ".search", "web."):
            cap = _make_cap(id=cap_id)
            errors = validate_registry(_make_registry(cap))
            id_errors = [e for e in errors if e.code == "invalid_capability_id_format"]
            assert id_errors, f"Expected error for id={cap_id!r}"

    def test_unknown_action_class_produces_error(self):
        cap = _make_cap(action_class="super_power")
        errors = validate_registry(_make_registry(cap))
        assert any(e.code == "unknown_action_class" for e in errors)

    def test_all_known_action_classes_pass(self):
        known = [
            "pure_read", "sensitive_read", "billable_read",
            "internal_mutation", "external_mutation",
            "irreversible_mutation", "privileged_control",
        ]
        for ac in known:
            cap = _make_cap(action_class=ac)
            errors = validate_registry(_make_registry(cap))
            ac_errors = [e for e in errors if e.code == "unknown_action_class"]
            assert ac_errors == [], f"Unexpected error for action_class={ac!r}"

    def test_invalid_compensable_value_produces_error(self):
        cap = _make_cap(compensable="maybe")
        errors = validate_registry(_make_registry(cap))
        assert any(e.code == "invalid_compensable_value" for e in errors)

    def test_compensable_true_is_valid(self):
        cap = _make_cap(compensable=True)
        errors = validate_registry(_make_registry(cap))
        comp_errors = [e for e in errors if e.code == "invalid_compensable_value"]
        assert comp_errors == []

    def test_compensable_false_is_valid(self):
        cap = _make_cap(compensable=False)
        errors = validate_registry(_make_registry(cap))
        comp_errors = [e for e in errors if e.code == "invalid_compensable_value"]
        assert comp_errors == []

    def test_compensable_na_string_is_valid(self):
        cap = _make_cap(compensable="na")
        errors = validate_registry(_make_registry(cap))
        comp_errors = [e for e in errors if e.code == "invalid_compensable_value"]
        assert comp_errors == []

    def test_error_has_source_file(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_duplicate_ids.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        dup = next(e for e in errors if e.code == "duplicate_capability_id")
        assert dup.source_file is not None
        assert "invalid_duplicate_ids.yaml" in dup.source_file

    def test_error_has_source_path(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_duplicate_ids.yaml")
        assert registry is not None
        errors = validate_registry(registry)
        dup = next(e for e in errors if e.code == "duplicate_capability_id")
        assert dup.source_path is not None
        assert "capabilities[" in dup.source_path


# ── Agent validation ──────────────────────────────────────────

class TestValidateAgent:

    def _valid_registry(self) -> LoadedRegistry:
        registry, errors = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert not errors
        assert registry is not None
        return registry

    def test_valid_agent_has_no_errors(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        assert errors == []

    def test_missing_capability_reference_error(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "invalid_missing_capability.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        codes = [e.code for e in errors]
        assert "unknown_capability_reference" in codes

    def test_missing_capability_error_message_golden(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "invalid_missing_capability.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        ref_err = next(e for e in errors if e.code == "unknown_capability_reference")
        assert ref_err.message == "unknown capability reference: nonexistent.capability"

    def test_loose_override_error(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "invalid_loose_override.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        codes = [e.code for e in errors]
        assert "loose_policy_override" in codes

    def test_loose_override_error_message_golden(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "invalid_loose_override.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        loose = next(e for e in errors if e.code == "loose_policy_override")
        assert loose.message == "policy override for data.delete is less strict than registry"

    def test_valid_agent_fixture_has_no_errors(self):
        registry = self._valid_registry()
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        errors = validate_agent(agent, registry)
        assert errors == []


# ── Stricter-only policy rule ─────────────────────────────────

class TestStricterOnlyRule:

    def _registry_with(self, **cap_kwargs) -> LoadedRegistry:
        cap = _make_cap(**cap_kwargs)
        return _make_registry(cap)

    def test_equal_policy_is_accepted(self):
        # irreversible_mutation default=confirm, agent sets confirm → OK
        registry = self._registry_with(
            id="data.delete", action_class="irreversible_mutation", compensable=False
        )
        agent = _make_agent(_grant("data.delete", "confirm"))
        errors = validate_agent(agent, registry)
        loose = [e for e in errors if e.code == "loose_policy_override"]
        assert loose == []

    def test_stricter_override_is_accepted(self):
        # external_mutation default=allow, agent sets confirm → stricter, OK
        registry = self._registry_with(id="tasks.write", action_class="external_mutation")
        agent = _make_agent(_grant("tasks.write", "confirm"))
        errors = validate_agent(agent, registry)
        loose = [e for e in errors if e.code == "loose_policy_override"]
        assert loose == []

    def test_deny_override_is_always_accepted(self):
        # deny is strictest; accepted for any default policy
        registry = self._registry_with(id="web.search", action_class="pure_read")
        agent = _make_agent(_grant("web.search", "deny"))
        errors = validate_agent(agent, registry)
        loose = [e for e in errors if e.code == "loose_policy_override"]
        assert loose == []

    def test_allow_override_on_confirm_default_is_rejected(self):
        # irreversible_mutation default=confirm, agent tries allow → loose
        registry = self._registry_with(
            id="data.delete", action_class="irreversible_mutation",
            compensable=False, justification_required=False,
        )
        agent = _make_agent(_grant("data.delete", "allow"))
        errors = validate_agent(agent, registry)
        assert any(e.code == "loose_policy_override" for e in errors)

    def test_confirm_override_on_deny_default_would_be_loose(self):
        # There is no action_class with deny default in the current taxonomy,
        # but the rule must hold if one is added; test via direct model construction.
        # We can't create such a case with existing action classes, so we test
        # that confirm < deny in the strictness ordering used by the validator.
        from agent_os.capabilities.validator import _POLICY_STRICTNESS
        assert _POLICY_STRICTNESS["confirm"] < _POLICY_STRICTNESS["deny"]
        assert _POLICY_STRICTNESS["allow"] < _POLICY_STRICTNESS["confirm"]

    def test_no_override_is_always_accepted(self):
        registry = self._registry_with(id="web.search", action_class="billable_read")
        agent = _make_agent(_grant("web.search", None))
        errors = validate_agent(agent, registry)
        loose = [e for e in errors if e.code == "loose_policy_override"]
        assert loose == []


# ── Governance seam: justification_required ───────────────────

class TestJustificationRequired:

    def test_justification_required_with_allow_is_error(self):
        cap = _make_cap(
            id="email.send",
            action_class="external_mutation",
            justification_required=True,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("email.send", None))  # effective=allow
        errors = validate_agent(agent, registry)
        assert any(e.code == "justification_required_violation" for e in errors)

    def test_justification_required_with_explicit_allow_is_error(self):
        cap = _make_cap(
            id="email.send",
            action_class="external_mutation",
            justification_required=True,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("email.send", "allow"))
        errors = validate_agent(agent, registry)
        assert any(e.code == "justification_required_violation" for e in errors)

    def test_justification_required_with_confirm_is_ok(self):
        cap = _make_cap(
            id="email.send",
            action_class="external_mutation",
            justification_required=True,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("email.send", "confirm"))
        errors = validate_agent(agent, registry)
        jv = [e for e in errors if e.code == "justification_required_violation"]
        assert jv == []

    def test_justification_required_with_deny_is_ok(self):
        cap = _make_cap(
            id="email.send",
            action_class="external_mutation",
            justification_required=True,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("email.send", "deny"))
        errors = validate_agent(agent, registry)
        jv = [e for e in errors if e.code == "justification_required_violation"]
        assert jv == []

    def test_justification_not_required_allows_allow(self):
        cap = _make_cap(id="web.search", justification_required=False)
        registry = _make_registry(cap)
        agent = _make_agent(_grant("web.search", None))
        errors = validate_agent(agent, registry)
        jv = [e for e in errors if e.code == "justification_required_violation"]
        assert jv == []


# ── Governance seam: compensable ─────────────────────────────

class TestCompensableGovernance:

    def test_noncompensable_irreversible_with_allow_is_error(self):
        cap = _make_cap(
            id="data.delete",
            action_class="irreversible_mutation",
            compensable=False,
            justification_required=False,
        )
        registry = _make_registry(cap)
        # data.delete default is confirm, but agent tries allow (also a loose override)
        agent = _make_agent(_grant("data.delete", "allow"))
        errors = validate_agent(agent, registry)
        assert any(e.code == "noncompensable_allow_policy" for e in errors)

    def test_noncompensable_internal_mutation_with_allow_is_ok(self):
        # compensable: false on internal_mutation (allow default) — no error
        # because internal_mutation is not in _IRREVERSIBLE_ACTION_CLASSES
        cap = _make_cap(
            id="memory.forget",
            action_class="internal_mutation",
            compensable=False,
            justification_required=False,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("memory.forget", None))
        errors = validate_agent(agent, registry)
        nc = [e for e in errors if e.code == "noncompensable_allow_policy"]
        assert nc == []

    def test_compensable_true_has_no_governance_error(self):
        cap = _make_cap(
            id="tasks.write",
            action_class="external_mutation",
            compensable=True,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("tasks.write", None))
        errors = validate_agent(agent, registry)
        nc = [e for e in errors if e.code == "noncompensable_allow_policy"]
        assert nc == []


# ── Governance seam: data_sensitivity ────────────────────────

class TestDataSensitivityGovernance:

    def test_sensitive_data_with_allow_produces_warning(self):
        cap = _make_cap(
            id="tasks.read",
            action_class="pure_read",
            data_sensitivity="internal",
            justification_required=False,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("tasks.read", None))
        errors = validate_agent(agent, registry)
        warn = [e for e in errors if e.code == "sensitive_data_allow_policy"]
        assert warn  # exists
        assert all(e.severity == "warning" for e in warn)

    def test_sensitive_data_warning_is_not_an_error(self):
        cap = _make_cap(
            id="tasks.read",
            action_class="pure_read",
            data_sensitivity="internal",
            justification_required=False,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("tasks.read", None))
        errors = validate_agent(agent, registry)
        fatal = [e for e in errors if e.severity == "error"]
        # no fatal errors from data_sensitivity alone
        assert not fatal

    def test_none_data_sensitivity_no_warning(self):
        cap = _make_cap(id="web.search", data_sensitivity="none")
        registry = _make_registry(cap)
        agent = _make_agent(_grant("web.search", None))
        errors = validate_agent(agent, registry)
        warn = [e for e in errors if e.code == "sensitive_data_allow_policy"]
        assert warn == []

    def test_financial_data_sensitivity_produces_warning(self):
        cap = _make_cap(
            id="finance.read",
            action_class="sensitive_read",
            data_sensitivity="financial",
            justification_required=False,
        )
        registry = _make_registry(cap)
        agent = _make_agent(_grant("finance.read", None))
        errors = validate_agent(agent, registry)
        warn = [e for e in errors if e.code == "sensitive_data_allow_policy"]
        assert warn


# ── Deterministic ordering ────────────────────────────────────

class TestDeterministicOrdering:

    def test_registry_capabilities_order_matches_yaml(self):
        registry, _ = load_registry(_CAP_FIX / "valid_registry.yaml")
        assert registry is not None
        ids = [c.id for c in registry.capabilities]
        # Must be in YAML source order, not sorted
        assert ids.index("web.search") < ids.index("tasks.read")
        assert ids.index("tasks.read") < ids.index("tasks.write")

    def test_agent_capabilities_order_matches_yaml(self):
        agent, _ = load_agent(_AGT_FIX / "valid_agent.yaml")
        assert agent is not None
        ids = [g.id for g in agent.spec.capabilities]
        assert ids.index("web.search") < ids.index("tasks.read")
        assert ids.index("tasks.read") < ids.index("tasks.write")

    def test_validate_registry_same_input_same_output(self):
        registry, _ = load_registry(_CAP_FIX / "invalid_duplicate_ids.yaml")
        assert registry is not None
        errors1 = validate_registry(registry)
        errors2 = validate_registry(registry)
        assert [e.code for e in errors1] == [e.code for e in errors2]
