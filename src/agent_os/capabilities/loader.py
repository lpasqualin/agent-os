"""Capability pack loader — reads YAML from disk into canonical models.

Two public functions:
    load_registry(path) -> (LoadedRegistry | None, list[ValidationError])
    load_agent(path)    -> (LoadedAgent | None,    list[ValidationError])

Both return a (result, errors) pair.
- If errors contain severity="error", the result may be None or partial.
- Errors with severity="warning" do not prevent a result from being returned.
- Never raises; all failures are captured as ValidationError entries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ValidationError
from .models import (
    AgentCapabilityGrant,
    AgentSpec,
    Capability,
    LoadedAgent,
    LoadedRegistry,
)

_REQUIRED_CAPABILITY_FIELDS = (
    "id",
    "action_class",
    "idempotent",
    "compensable",
    "data_sensitivity",
    "justification_required",
)

_REQUIRED_AGENT_FIELDS = ("id", "name", "version")


# ── Registry ──────────────────────────────────────────────────


def load_registry(path: Path) -> tuple[LoadedRegistry | None, list[ValidationError]]:
    """Load and parse a capability registry YAML file."""
    errors: list[ValidationError] = []
    src = str(path)

    raw_text, read_errors = _read_file(path, src)
    if read_errors:
        return None, read_errors

    data, parse_errors = _parse_yaml(raw_text, src)  # type: ignore[arg-type]
    if parse_errors:
        return None, parse_errors

    if not isinstance(data, dict):
        return None, [ValidationError(
            code="invalid_structure",
            message="registry must be a YAML mapping",
            source_file=src,
            severity="error",
        )]

    raw_caps = data.get("capabilities")
    if raw_caps is None:
        return None, [ValidationError(
            code="missing_required_field",
            message="missing required field: capabilities",
            source_file=src,
            severity="error",
        )]

    if not isinstance(raw_caps, list):
        return None, [ValidationError(
            code="invalid_structure",
            message="capabilities must be a list",
            source_file=src,
            severity="error",
        )]

    capabilities: list[Capability] = []
    for i, raw in enumerate(raw_caps):
        cap, cap_errors = _parse_capability(raw, src, f"capabilities[{i}]")
        errors.extend(cap_errors)
        if cap is not None:
            capabilities.append(cap)

    return LoadedRegistry(capabilities=capabilities, source_file=src), errors


def _parse_capability(
    raw: Any, source_file: str, path: str
) -> tuple[Capability | None, list[ValidationError]]:
    errors: list[ValidationError] = []

    if not isinstance(raw, dict):
        return None, [ValidationError(
            code="invalid_structure",
            message=f"capability entry must be a mapping, got {type(raw).__name__}",
            source_file=source_file,
            source_path=path,
            severity="error",
        )]

    missing = [f for f in _REQUIRED_CAPABILITY_FIELDS if f not in raw]
    if missing:
        for field_name in missing:
            errors.append(ValidationError(
                code="missing_required_field",
                message=f"missing required field: {field_name} in {path}",
                source_file=source_file,
                source_path=path,
                severity="error",
            ))
        return None, errors

    compensable = raw["compensable"]
    # Normalise: YAML parses `na` (unquoted) and `"na"` both as str "na"
    if isinstance(compensable, str) and compensable.lower() == "na":
        compensable = "na"

    cap = Capability(
        id=str(raw["id"]),
        action_class=str(raw["action_class"]),
        idempotent=bool(raw["idempotent"]),
        compensable=compensable,
        data_sensitivity=str(raw["data_sensitivity"]),
        justification_required=bool(raw["justification_required"]),
    )
    return cap, errors


# ── Agent spec ────────────────────────────────────────────────


def load_agent(path: Path) -> tuple[LoadedAgent | None, list[ValidationError]]:
    """Load and parse an agent spec YAML file."""
    errors: list[ValidationError] = []
    src = str(path)

    raw_text, read_errors = _read_file(path, src)
    if read_errors:
        return None, read_errors

    data, parse_errors = _parse_yaml(raw_text, src)  # type: ignore[arg-type]
    if parse_errors:
        return None, parse_errors

    if not isinstance(data, dict):
        return None, [ValidationError(
            code="invalid_structure",
            message="agent spec must be a YAML mapping",
            source_file=src,
            severity="error",
        )]

    missing = [f for f in _REQUIRED_AGENT_FIELDS if f not in data]
    if missing:
        for field_name in missing:
            errors.append(ValidationError(
                code="missing_required_field",
                message=f"missing required field: {field_name}",
                source_file=src,
                severity="error",
            ))
        return None, errors

    raw_caps = data.get("capabilities") or []
    if not isinstance(raw_caps, list):
        errors.append(ValidationError(
            code="invalid_structure",
            message="capabilities must be a list",
            source_file=src,
            severity="error",
        ))
        raw_caps = []

    grants: list[AgentCapabilityGrant] = []
    for i, raw in enumerate(raw_caps):
        grant, grant_errors = _parse_grant(raw, src, f"capabilities[{i}]")
        errors.extend(grant_errors)
        if grant is not None:
            grants.append(grant)

    spec = AgentSpec(
        agent_id=str(data["id"]),
        name=str(data["name"]),
        version=str(data["version"]),
        capabilities=grants,
    )
    return LoadedAgent(spec=spec, source_file=src), errors


def _parse_grant(
    raw: Any, source_file: str, path: str
) -> tuple[AgentCapabilityGrant | None, list[ValidationError]]:
    if not isinstance(raw, dict):
        return None, [ValidationError(
            code="invalid_structure",
            message="capability entry must be a mapping",
            source_file=source_file,
            source_path=path,
            severity="error",
        )]

    if "id" not in raw:
        return None, [ValidationError(
            code="missing_required_field",
            message=f"missing required field: id in {path}",
            source_file=source_file,
            source_path=path,
            severity="error",
        )]

    policy = raw.get("policy")
    policy_override = str(policy) if policy is not None else None

    return AgentCapabilityGrant(id=str(raw["id"]), policy_override=policy_override), []


# ── Helpers ───────────────────────────────────────────────────


def _read_file(path: Path, src: str) -> tuple[str | None, list[ValidationError]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except OSError as exc:
        return None, [ValidationError(
            code="file_read_error",
            message=f"cannot read file: {exc}",
            source_file=src,
            severity="error",
        )]


def _parse_yaml(text: str, src: str) -> tuple[Any | None, list[ValidationError]]:
    try:
        return yaml.safe_load(text), []
    except yaml.YAMLError as exc:
        return None, [ValidationError(
            code="invalid_yaml",
            message=f"invalid YAML: {exc}",
            source_file=src,
            severity="error",
        )]
