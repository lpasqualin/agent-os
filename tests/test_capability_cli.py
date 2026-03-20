"""Tests for capability CLI commands.

Tests cmd_validate_registry, cmd_validate_agent, cmd_show_agent_capabilities
via direct function calls (no subprocess). Uses fixture files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_os.capabilities.commands import (
    cmd_show_agent_capabilities,
    cmd_validate_agent,
    cmd_validate_registry,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_CAP_FIX  = _FIXTURES / "capabilities"
_AGT_FIX  = _FIXTURES / "agents"

_VALID_REGISTRY  = str(_CAP_FIX / "valid_registry.yaml")
_DUP_IDS         = str(_CAP_FIX / "invalid_duplicate_ids.yaml")
_BAD_FORMAT      = str(_CAP_FIX / "invalid_bad_id_format.yaml")
_VALID_AGENT     = str(_AGT_FIX / "valid_agent.yaml")
_MISSING_CAP     = str(_AGT_FIX / "invalid_missing_capability.yaml")
_LOOSE_OVERRIDE  = str(_AGT_FIX / "invalid_loose_override.yaml")


def _args(**kwargs) -> argparse.Namespace:
    defaults = dict(registry=_VALID_REGISTRY)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── validate-registry ─────────────────────────────────────────

class TestCmdValidateRegistry:

    def test_valid_registry_exits_zero(self, capsys):
        args = _args(registry_path=_VALID_REGISTRY)
        rc = cmd_validate_registry(args)
        assert rc == 0

    def test_valid_registry_prints_ok(self, capsys):
        args = _args(registry_path=_VALID_REGISTRY)
        cmd_validate_registry(args)
        out = capsys.readouterr().out
        assert "OK" in out

    def test_duplicate_ids_exits_nonzero(self, capsys):
        args = _args(registry_path=_DUP_IDS)
        rc = cmd_validate_registry(args)
        assert rc != 0

    def test_duplicate_ids_prints_error(self, capsys):
        args = _args(registry_path=_DUP_IDS)
        cmd_validate_registry(args)
        out = capsys.readouterr().out
        assert "ERROR" in out

    def test_duplicate_ids_error_message_in_output(self, capsys):
        args = _args(registry_path=_DUP_IDS)
        cmd_validate_registry(args)
        out = capsys.readouterr().out
        assert "duplicate capability id: tasks.write" in out

    def test_bad_id_format_exits_nonzero(self, capsys):
        args = _args(registry_path=_BAD_FORMAT)
        rc = cmd_validate_registry(args)
        assert rc != 0

    def test_bad_id_format_error_message_in_output(self, capsys):
        args = _args(registry_path=_BAD_FORMAT)
        cmd_validate_registry(args)
        out = capsys.readouterr().out
        assert "invalid capability id format: Gmail.Send" in out

    def test_missing_registry_file_exits_nonzero(self, tmp_path, capsys):
        args = _args(registry_path=str(tmp_path / "no.yaml"))
        rc = cmd_validate_registry(args)
        assert rc != 0

    def test_missing_registry_file_prints_error(self, tmp_path, capsys):
        args = _args(registry_path=str(tmp_path / "no.yaml"))
        cmd_validate_registry(args)
        out = capsys.readouterr().out
        assert "ERROR" in out


# ── validate-agent ────────────────────────────────────────────

class TestCmdValidateAgent:

    def test_valid_agent_exits_zero(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        rc = cmd_validate_agent(args)
        assert rc == 0

    def test_valid_agent_prints_ok(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_validate_agent(args)
        out = capsys.readouterr().out
        assert "OK" in out

    def test_missing_capability_exits_nonzero(self, capsys):
        args = _args(agent_path=_MISSING_CAP, registry=_VALID_REGISTRY)
        rc = cmd_validate_agent(args)
        assert rc != 0

    def test_missing_capability_error_in_output(self, capsys):
        args = _args(agent_path=_MISSING_CAP, registry=_VALID_REGISTRY)
        cmd_validate_agent(args)
        out = capsys.readouterr().out
        assert "unknown capability reference: nonexistent.capability" in out

    def test_loose_override_exits_nonzero(self, capsys):
        args = _args(agent_path=_LOOSE_OVERRIDE, registry=_VALID_REGISTRY)
        rc = cmd_validate_agent(args)
        assert rc != 0

    def test_loose_override_error_in_output(self, capsys):
        args = _args(agent_path=_LOOSE_OVERRIDE, registry=_VALID_REGISTRY)
        cmd_validate_agent(args)
        out = capsys.readouterr().out
        assert "policy override for data.delete is less strict than registry" in out

    def test_missing_agent_file_exits_nonzero(self, tmp_path, capsys):
        args = _args(agent_path=str(tmp_path / "no.yaml"), registry=_VALID_REGISTRY)
        rc = cmd_validate_agent(args)
        assert rc != 0

    def test_missing_registry_exits_nonzero(self, tmp_path, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=str(tmp_path / "no.yaml"))
        rc = cmd_validate_agent(args)
        assert rc != 0

    def test_validate_failure_prints_validation_failed(self, capsys):
        args = _args(agent_path=_MISSING_CAP, registry=_VALID_REGISTRY)
        cmd_validate_agent(args)
        out = capsys.readouterr().out
        assert "Validation FAILED" in out


# ── show-agent-capabilities ───────────────────────────────────

class TestCmdShowAgentCapabilities:

    def test_valid_agent_exits_zero(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        rc = cmd_show_agent_capabilities(args)
        assert rc == 0

    def test_output_contains_agent_id(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_show_agent_capabilities(args)
        out = capsys.readouterr().out
        assert "test-agent" in out

    def test_output_contains_all_capability_ids(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_show_agent_capabilities(args)
        out = capsys.readouterr().out
        for cap_id in ("web.search", "tasks.read", "tasks.write", "data.delete"):
            assert cap_id in out

    def test_output_contains_effective_policy(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_show_agent_capabilities(args)
        out = capsys.readouterr().out
        # tasks.write has policy: confirm override
        assert "confirm" in out

    def test_output_contains_header_columns(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_show_agent_capabilities(args)
        out = capsys.readouterr().out
        assert "CAPABILITY" in out
        assert "POLICY" in out

    def test_output_shows_agent_name_and_version(self, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=_VALID_REGISTRY)
        cmd_show_agent_capabilities(args)
        out = capsys.readouterr().out
        assert "Test Agent" in out
        assert "1.0.0" in out

    def test_missing_agent_file_exits_nonzero(self, tmp_path, capsys):
        args = _args(agent_path=str(tmp_path / "no.yaml"), registry=_VALID_REGISTRY)
        rc = cmd_show_agent_capabilities(args)
        assert rc != 0

    def test_missing_registry_exits_nonzero(self, tmp_path, capsys):
        args = _args(agent_path=_VALID_AGENT, registry=str(tmp_path / "no.yaml"))
        rc = cmd_show_agent_capabilities(args)
        assert rc != 0


# ── Warning output ────────────────────────────────────────────

class TestWarningOutput:

    def test_warning_does_not_cause_nonzero_exit(self, tmp_path, capsys):
        """A registry/agent that produces only warnings should still exit 0."""
        # Build a registry with a sensitive capability
        reg = tmp_path / "reg.yaml"
        reg.write_text(
            "capabilities:\n"
            "  - id: tasks.read\n"
            "    action_class: pure_read\n"
            "    idempotent: true\n"
            "    compensable: na\n"
            "    data_sensitivity: internal\n"  # sensitive → warning on allow
            "    justification_required: false\n"
        )
        agent = tmp_path / "agent.yaml"
        agent.write_text(
            "id: warn-agent\n"
            "name: Warn Agent\n"
            "version: 1.0.0\n"
            "capabilities:\n"
            "  - id: tasks.read\n"  # no override → effective allow → warning
        )
        args = _args(agent_path=str(agent), registry=str(reg))
        rc = cmd_validate_agent(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "WARNING" in out
        assert "OK" in out
