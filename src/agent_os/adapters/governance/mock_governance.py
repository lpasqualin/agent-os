"""Mock governance adapter — two-tier enforcement with policy evaluation.

Tier 1: Automatic policy check (fast, in-process)
Tier 2: Human approval (mocked as auto-approve for Phase 1)
"""

from datetime import datetime, timezone

from agent_os.adapters.interfaces import GovernanceAdapter
from agent_os.contracts.models import (
    ActionClass,
    Policy,
    ACTION_CLASS_DEFAULT_POLICY,
    CapabilityRegistry,
    AgentSpec,
)


class MockGovernance(GovernanceAdapter):

    def __init__(self, registry: CapabilityRegistry, spec: AgentSpec):
        self._registry = registry
        self._spec = spec
        self._audit: list[dict] = []
        self._budget_used: float = 0.0

        # Build resolved policy map: capability_id -> effective policy
        self._policy_map: dict[str, Policy] = {}
        for cap_ref in spec.capabilities:
            cap_def = registry.get(cap_ref.id)
            if cap_def:
                # Use spec override if provided, otherwise action_class default
                self._policy_map[cap_ref.id] = cap_ref.policy or cap_def.default_policy
            else:
                self._policy_map[cap_ref.id] = Policy.DENY  # unknown = deny

    def evaluate(self, agent_id: str, action: str, context: dict | None = None) -> str:
        """Tier 1: Fast automatic policy evaluation."""
        cap_def = self._registry.get(action)
        if cap_def is None:
            return "deny"  # unknown capability = deny

        # pure_read is exempt from governance
        if cap_def.action_class == ActionClass.PURE_READ:
            return "allow"

        # Check budget
        if self._spec.governance and self._spec.governance.spend_limit:
            limit = self._spec.governance.spend_limit.daily_usd
            if limit and self._budget_used >= limit:
                return "deny"  # budget exceeded

        # Check resolved policy
        policy = self._policy_map.get(action, Policy.DENY)
        if policy == Policy.DENY:
            return "deny"
        elif policy == Policy.CONFIRM:
            return "require_approval"
        else:
            return "allow"

    def request_approval(self, agent_id: str, action: str, context: dict | None = None) -> str:
        """Tier 2: Human approval — mock auto-approves for Phase 1."""
        # In real implementation, this sends to Telegram and blocks.
        # For mock, auto-approve.
        return "approved"

    def audit_log(self, agent_id: str, run_id: str, action: str, result: str, metadata: dict | None = None) -> None:
        """Append-only audit record."""
        self._audit.append({
            "seq": len(self._audit) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "run_id": run_id,
            "action": action,
            "result": result,
            "metadata": metadata or {},
        })

    def check_budget(self, agent_id: str) -> dict:
        limit = None
        if self._spec.governance and self._spec.governance.spend_limit:
            limit = self._spec.governance.spend_limit.daily_usd
        return {
            "daily_limit_usd": limit,
            "used_usd": self._budget_used,
            "remaining_usd": (limit - self._budget_used) if limit else None,
        }

    def health(self) -> dict:
        return {
            "status": "ok",
            "backend": "mock",
            "audit_entries": len(self._audit),
        }
