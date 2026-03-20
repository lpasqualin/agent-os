"""Capability validator — structural and semantic checks.

Two public functions:
    validate_registry(registry) -> list[ValidationError]
    validate_agent(agent, registry) -> list[ValidationError]

Validation is pure: no I/O, no side effects, no mutation of inputs.

Governance seam — stricter-only override rule (explicit, test-backed):
  1. policy_override must be >= the capability's registry default policy
     (policy strictness: allow=0 < confirm=1 < deny=2)
  2. justification_required: true in registry → effective policy must be
     confirm or deny; allow is rejected
  3. compensable: false in registry → effective policy must be confirm or
     deny for irreversible actions; allow with allow-default is rejected
  4. data_sensitivity in sensitive set → advisory warning when policy is allow
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .errors import ValidationError
from .models import Capability, LoadedAgent, LoadedRegistry

if TYPE_CHECKING:
    from .models import AgentCapabilityGrant

# ── Constants ─────────────────────────────────────────────────

_CAPABILITY_ID_RE = re.compile(r"^[a-z]+\.[a-z]+$")

_POLICY_STRICTNESS: dict[str, int] = {
    "allow":   0,
    "confirm": 1,
    "deny":    2,
}

_ACTION_CLASS_DEFAULT_POLICY: dict[str, str] = {
    "pure_read":             "allow",
    "sensitive_read":        "allow",
    "billable_read":         "allow",
    "internal_mutation":     "allow",
    "external_mutation":     "allow",
    "irreversible_mutation": "confirm",
    "privileged_control":    "confirm",
}

# data_sensitivity values that trigger the advisory governance warning
_SENSITIVE_DATA_CLASSES: frozenset[str] = frozenset({
    "internal", "personal", "regulated", "financial",
})

# action classes where compensable:false + allow policy is an error
# (irreversible_mutation already defaults to confirm, so this catches allow
#  overrides on those capabilities and any other non-compensable+allow combo)
_IRREVERSIBLE_ACTION_CLASSES: frozenset[str] = frozenset({
    "irreversible_mutation",
    "privileged_control",
})


# ── Registry validation ───────────────────────────────────────


def validate_registry(registry: LoadedRegistry) -> list[ValidationError]:
    """Validate a loaded capability registry.

    Checks:
      - capability id format
      - duplicate ids
      - known action_class values
      - compensable field is bool or "na"
    """
    errors: list[ValidationError] = []
    src = registry.source_file
    seen_ids: set[str] = set()

    for i, cap in enumerate(registry.capabilities):
        path = f"capabilities[{i}]"

        # id format
        if not _CAPABILITY_ID_RE.match(cap.id):
            errors.append(ValidationError(
                code="invalid_capability_id_format",
                message=f"invalid capability id format: {cap.id}",
                source_file=src,
                source_path=path,
                severity="error",
            ))

        # duplicate ids
        if cap.id in seen_ids:
            errors.append(ValidationError(
                code="duplicate_capability_id",
                message=f"duplicate capability id: {cap.id}",
                source_file=src,
                source_path=path,
                severity="error",
            ))
        seen_ids.add(cap.id)

        # known action_class
        if cap.action_class not in _ACTION_CLASS_DEFAULT_POLICY:
            errors.append(ValidationError(
                code="unknown_action_class",
                message=f"unknown action_class: {cap.action_class}",
                source_file=src,
                source_path=path,
                severity="error",
            ))

        # compensable: must be bool or "na"
        if not isinstance(cap.compensable, bool) and cap.compensable != "na":
            errors.append(ValidationError(
                code="invalid_compensable_value",
                message=(
                    f"compensable must be true, false, or 'na', "
                    f"got: {cap.compensable!r}"
                ),
                source_file=src,
                source_path=path,
                severity="error",
            ))

    return errors


# ── Agent validation ──────────────────────────────────────────


def validate_agent(
    agent: LoadedAgent,
    registry: LoadedRegistry,
) -> list[ValidationError]:
    """Validate an agent spec against a capability registry.

    Checks:
      - capability id format in agent spec
      - capability references exist in registry
      - policy overrides are only stricter (never looser) than registry default
      - governance seam: justification_required, compensable, data_sensitivity
    """
    errors: list[ValidationError] = []
    src = agent.source_file
    registry_index: dict[str, Capability] = {c.id: c for c in registry.capabilities}

    for i, grant in enumerate(agent.spec.capabilities):
        path = f"capabilities[{i}]"

        # id format
        if not _CAPABILITY_ID_RE.match(grant.id):
            errors.append(ValidationError(
                code="invalid_capability_id_format",
                message=f"invalid capability id format: {grant.id}",
                source_file=src,
                source_path=path,
                severity="error",
            ))
            continue

        # capability must exist in registry
        cap = registry_index.get(grant.id)
        if cap is None:
            errors.append(ValidationError(
                code="unknown_capability_reference",
                message=f"unknown capability reference: {grant.id}",
                source_file=src,
                source_path=path,
                severity="error",
            ))
            continue

        # policy override strictness
        if grant.policy_override is not None:
            errors.extend(_check_policy_override(grant, cap, src, path))

        # governance seam checks (applied with the effective policy)
        effective = grant.policy_override or _ACTION_CLASS_DEFAULT_POLICY.get(
            cap.action_class, "allow"
        )
        errors.extend(_check_governance(grant.id, cap, effective, src, path))

    return errors


def _check_policy_override(
    grant: "AgentCapabilityGrant",
    cap: Capability,
    source_file: str | None,
    path: str,
) -> list[ValidationError]:
    override = grant.policy_override
    assert override is not None  # guard for type checker

    if override not in _POLICY_STRICTNESS:
        return [ValidationError(
            code="unknown_policy_value",
            message=f"unknown policy value: {override!r}",
            source_file=source_file,
            source_path=path,
            severity="error",
        )]

    default = _ACTION_CLASS_DEFAULT_POLICY.get(cap.action_class, "allow")
    if _POLICY_STRICTNESS[override] < _POLICY_STRICTNESS[default]:
        return [ValidationError(
            code="loose_policy_override",
            message=f"policy override for {grant.id} is less strict than registry",
            source_file=source_file,
            source_path=path,
            severity="error",
        )]

    return []


def _check_governance(
    cap_id: str,
    cap: Capability,
    effective_policy: str,
    source_file: str | None,
    path: str,
) -> list[ValidationError]:
    """Governance seam checks applied after policy resolution."""
    errors: list[ValidationError] = []

    # justification_required: true → effective policy must be confirm or deny
    if cap.justification_required and effective_policy == "allow":
        errors.append(ValidationError(
            code="justification_required_violation",
            message=(
                f"capability {cap_id} requires justification "
                f"but policy is allow"
            ),
            source_file=source_file,
            source_path=path,
            severity="error",
        ))

    # compensable: false on irreversible action classes → allow is too loose
    if (
        cap.compensable is False
        and cap.action_class in _IRREVERSIBLE_ACTION_CLASSES
        and effective_policy == "allow"
    ):
        errors.append(ValidationError(
            code="noncompensable_allow_policy",
            message=(
                f"capability {cap_id} is non-compensable "
                f"(action_class={cap.action_class}) but policy is allow"
            ),
            source_file=source_file,
            source_path=path,
            severity="error",
        ))

    # data_sensitivity: sensitive → advisory warning when allow
    if (
        cap.data_sensitivity in _SENSITIVE_DATA_CLASSES
        and effective_policy == "allow"
        and not cap.justification_required  # already reported above if True
    ):
        errors.append(ValidationError(
            code="sensitive_data_allow_policy",
            message=(
                f"capability {cap_id} has data_sensitivity={cap.data_sensitivity} "
                f"but policy is allow"
            ),
            source_file=source_file,
            source_path=path,
            severity="warning",
        ))

    return errors
