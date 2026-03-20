"""Registry validator — Pass B: semantic validation.

Cross-checks an agent spec against the capability registry.
Catches: unknown capabilities, policy overrides that are too permissive,
approval gate inconsistencies.
"""

from agent_os.contracts.models import (
    AgentSpec,
    CapabilityRegistry,
    Policy,
    POLICY_STRICTNESS,
)
from agent_os.validators.schema_validator import ValidationResult


def validate_registry(spec: AgentSpec, registry: CapabilityRegistry) -> ValidationResult:
    """Pass B: Validate agent spec semantics against the capability registry.

    Assumes spec has already passed structural validation (Pass A).
    """
    result = ValidationResult(passed=True)
    registry_ids = registry.ids()

    for cap_ref in spec.capabilities:
        # 1. Check capability exists in registry
        cap_def = registry.get(cap_ref.id)
        if cap_def is None:
            result.passed = False
            result.errors.append(
                f"Unknown capability '{cap_ref.id}' — not found in registry. "
                f"Available: {sorted(registry_ids)}"
            )
            continue

        # 2. Check policy override is not more permissive than default
        if cap_ref.policy is not None:
            default_policy = cap_def.default_policy
            override_strictness = POLICY_STRICTNESS[cap_ref.policy]
            default_strictness = POLICY_STRICTNESS[default_policy]

            if override_strictness < default_strictness:
                result.passed = False
                result.errors.append(
                    f"Capability '{cap_ref.id}': policy override '{cap_ref.policy.value}' "
                    f"is MORE permissive than action_class default "
                    f"'{default_policy.value}' (action_class: {cap_def.action_class.value}). "
                    f"Overrides may only be stricter."
                )

    # 3. Check approval_gates reference valid confirm capabilities
    if spec.governance and spec.governance.approval_gates:
        spec_cap_ids = spec.capability_ids()
        for gate_id in spec.governance.approval_gates:
            if gate_id not in spec_cap_ids:
                result.passed = False
                result.errors.append(
                    f"Approval gate '{gate_id}' is not declared in capabilities."
                )
                continue

            # Find the capability ref to check its policy
            cap_ref = next(c for c in spec.capabilities if c.id == gate_id)
            if cap_ref.policy != Policy.CONFIRM:
                result.warnings.append(
                    f"Approval gate '{gate_id}' is listed but capability policy "
                    f"is '{cap_ref.policy.value}', not 'confirm'. "
                    f"Gate will have no effect unless policy is 'confirm'."
                )

    return result
