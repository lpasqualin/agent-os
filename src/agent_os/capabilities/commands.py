"""CLI command implementations for capability pack operations.

Commands:
    cmd_validate_registry(args) -> int
    cmd_validate_agent(args)    -> int
    cmd_show_agent_capabilities(args) -> int

Each returns an exit code: 0 = success, 1 = validation failure or error.
Errors are printed to stdout; warnings are labelled but do not cause non-zero exit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .errors import ValidationError
from .loader import load_agent, load_registry
from .validator import validate_registry, validate_agent


# ── validate-registry ─────────────────────────────────────────


def cmd_validate_registry(args: argparse.Namespace) -> int:
    """Validate a capability registry YAML file."""
    path = Path(args.registry_path)
    registry, load_errors = load_registry(path)

    errors = load_errors[:]
    if registry is not None:
        errors.extend(validate_registry(registry))

    return _report("registry", str(path), errors)


# ── validate-agent ────────────────────────────────────────────


def cmd_validate_agent(args: argparse.Namespace) -> int:
    """Validate an agent spec YAML against a capability registry."""
    from agent_os.capabilities.loader import load_registry as _lr

    agent_path = Path(args.agent_path)
    registry_path = Path(args.registry) if args.registry else _default_registry()

    registry, reg_errors = _lr(registry_path)
    agent, agent_errors = load_agent(agent_path)

    all_errors = reg_errors + agent_errors
    if registry is not None and agent is not None:
        all_errors.extend(validate_agent(agent, registry))

    return _report("agent", str(agent_path), all_errors)


# ── show-agent-capabilities ───────────────────────────────────


def cmd_show_agent_capabilities(args: argparse.Namespace) -> int:
    """Print a capability table for an agent spec."""
    from agent_os.capabilities.loader import load_registry as _lr
    from agent_os.capabilities.validator import (
        _ACTION_CLASS_DEFAULT_POLICY,
        _POLICY_STRICTNESS,
    )

    agent_path = Path(args.agent_path)
    registry_path = Path(args.registry) if args.registry else _default_registry()

    registry, reg_errors = _lr(registry_path)
    agent, agent_errors = load_agent(agent_path)

    # Fail if loader errors prevent display
    fatal = [e for e in reg_errors + agent_errors if e.severity == "error"]
    if fatal:
        for err in fatal:
            print(f"ERROR: {err}")
        return 1

    assert agent is not None
    assert registry is not None

    reg_index = {c.id: c for c in registry.capabilities}
    spec = agent.spec

    print(f"Agent:  {spec.agent_id}  ({spec.name} v{spec.version})")
    print()

    col_id  = max((len(g.id) for g in spec.capabilities), default=10)
    col_id  = max(col_id, len("CAPABILITY"))
    header  = f"  {'CAPABILITY':<{col_id}}  {'POLICY':<9}  {'OVERRIDE':<8}  {'JUSTIF':<6}  COMPENSABLE"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for grant in spec.capabilities:
        cap = reg_index.get(grant.id)
        if cap is None:
            print(f"  {grant.id:<{col_id}}  {'?':<9}  {'?':<8}  {'?':<6}  ?  [unknown]")
            continue

        default = _ACTION_CLASS_DEFAULT_POLICY.get(cap.action_class, "allow")
        effective = grant.policy_override or default
        override_marker = "*" if grant.policy_override else " "
        justif = "yes" if cap.justification_required else "no"
        comp   = str(cap.compensable)

        print(
            f"  {grant.id:<{col_id}}  "
            f"{effective:<9}"
            f"{override_marker:<8}  "
            f"{justif:<6}  "
            f"{comp}"
        )

    print()
    return 0


# ── Helpers ───────────────────────────────────────────────────


def _default_registry() -> Path:
    """Walk up from CWD to find the project's capabilities/registry.yaml."""
    from agent_os.cli import find_project_root
    return find_project_root() / "capabilities" / "registry.yaml"


def _report(kind: str, path: str, errors: list[ValidationError]) -> int:
    fatal   = [e for e in errors if e.severity == "error"]
    warnings = [e for e in errors if e.severity == "warning"]

    for w in warnings:
        print(f"WARNING: {w.message}")
    for e in fatal:
        print(f"ERROR: {e.message}")

    if fatal:
        print(f"\nValidation FAILED ({len(fatal)} error(s))")
        return 1

    if warnings:
        print(f"\nOK ({kind}: {path}) — {len(warnings)} warning(s)")
    else:
        print(f"OK ({kind}: {path})")
    return 0
