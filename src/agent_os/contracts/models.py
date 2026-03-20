"""Agent OS contract models — Pydantic representations of constitutional contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Runtime execution contract ────────────────────────────────

class RuntimeStatus(str, Enum):
    """Closed set of terminal statuses for a runtime execution result.

    These are the only valid outcomes an adapter may report. The chassis
    maps each to the appropriate lifecycle state transition.
    """
    SUCCEEDED = "succeeded"
    FAILED    = "failed"
    REJECTED  = "rejected"   # capability or policy rejected before invocation
    TIMED_OUT = "timed_out"  # invocation exceeded timeout; lifecycle → failed


class RuntimeExecutionResult(BaseModel):
    """Strict result shape returned by RuntimeAdapter.execute().

    Every field is required except raw_response (debug only).
    The chassis validates this shape before advancing the run lifecycle.
    """
    run_id:       str
    status:       RuntimeStatus
    capability:   str
    tool_name:    Optional[str]  = None
    output:       Optional[str]  = None
    error:        Optional[str]  = None
    started_at:   datetime
    finished_at:  datetime
    duration_ms:  int
    raw_response: Optional[dict] = None   # debug only — do not surface to users
    metadata:     dict           = Field(default_factory=dict)


# ── Enums ────────────────────────────────────────────────────

class Policy(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class MemoryScope(str, Enum):
    AGENT = "agent"
    SHARED = "shared"
    GLOBAL = "global"


class ActionClass(str, Enum):
    PURE_READ = "pure_read"
    SENSITIVE_READ = "sensitive_read"
    BILLABLE_READ = "billable_read"
    INTERNAL_MUTATION = "internal_mutation"
    EXTERNAL_MUTATION = "external_mutation"
    IRREVERSIBLE_MUTATION = "irreversible_mutation"
    PRIVILEGED_CONTROL = "privileged_control"


class DataSensitivity(str, Enum):
    NONE = "none"
    INTERNAL = "internal"
    PERSONAL = "personal"
    REGULATED = "regulated"
    FINANCIAL = "financial"
    VARIES = "varies"


# Strictness ordering: allow < confirm < deny
POLICY_STRICTNESS = {
    Policy.ALLOW: 0,
    Policy.CONFIRM: 1,
    Policy.DENY: 2,
}

# Default governance policy per action class (from constitution §3)
ACTION_CLASS_DEFAULT_POLICY = {
    ActionClass.PURE_READ: Policy.ALLOW,
    ActionClass.SENSITIVE_READ: Policy.ALLOW,
    ActionClass.BILLABLE_READ: Policy.ALLOW,
    ActionClass.INTERNAL_MUTATION: Policy.ALLOW,
    ActionClass.EXTERNAL_MUTATION: Policy.ALLOW,  # constitution: "confirm for unvetted, allow for established" — allow is the base default, specs escalate as needed
    ActionClass.IRREVERSIBLE_MUTATION: Policy.CONFIRM,
    ActionClass.PRIVILEGED_CONTROL: Policy.CONFIRM,
}


# ── Registry Models ──────────────────────────────────────────

class CapabilityDefinition(BaseModel):
    """A capability as defined in the registry — the semantic source of truth."""

    id: str
    action_class: ActionClass
    idempotent: bool
    compensable: bool | str  # bool or "na"
    data_sensitivity: DataSensitivity
    justification_required: bool

    @field_validator("id")
    @classmethod
    def validate_domain_verb(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 2 or not parts[0].isalpha() or not parts[1].isalpha():
            raise ValueError(
                f"Capability ID must be domain.verb format, got: '{v}'"
            )
        return v

    @property
    def default_policy(self) -> Policy:
        return ACTION_CLASS_DEFAULT_POLICY[self.action_class]


class CapabilityRegistry(BaseModel):
    """The full capability registry — loaded from capabilities/registry.yaml."""

    capabilities: list[CapabilityDefinition]

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        for cap in self.capabilities:
            if cap.id == capability_id:
                return cap
        return None

    def ids(self) -> set[str]:
        return {cap.id for cap in self.capabilities}


# ── Agent Spec Models ────────────────────────────────────────

class CapabilityRef(BaseModel):
    """A capability reference in an agent spec."""

    id: str
    policy: Optional[Policy] = None
    required: bool = False

    @field_validator("id")
    @classmethod
    def validate_domain_verb(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) != 2 or not parts[0].isalpha() or not parts[1].isalpha():
            raise ValueError(
                f"Capability ID must be domain.verb format, got: '{v}'"
            )
        return v


class Identity(BaseModel):
    soul: Optional[str] = None
    user_context: Optional[str] = None


class Channel(BaseModel):
    type: str
    config: Optional[str] = None


class Models(BaseModel):
    primary: Optional[str] = None
    fallback: list[str] = Field(default_factory=list)
    local: list[str] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    backend: str = "default"
    scope: MemoryScope = MemoryScope.AGENT
    config: Optional[str] = None


class ObservabilityConfig(BaseModel):
    backend: str = "default"
    config: Optional[str] = None


class SpendLimit(BaseModel):
    daily_usd: Optional[float] = None
    monthly_usd: Optional[float] = None


class GovernanceConfig(BaseModel):
    spend_limit: Optional[SpendLimit] = None
    approval_gates: list[str] = Field(default_factory=list)
    role: Optional[str] = None


class ScheduleEntry(BaseModel):
    cron: str
    task: str


class RuntimeConfig(BaseModel):
    target: str
    config: Optional[str] = None


class AgentSpec(BaseModel):
    """A complete agent specification — the portable unit of the Agent OS."""

    id: str
    name: str
    version: str
    identity: Optional[Identity] = None
    channels: list[Channel] = Field(default_factory=list)
    models: Optional[Models] = None
    capabilities: list[CapabilityRef]
    memory: Optional[MemoryConfig] = None
    observability: Optional[ObservabilityConfig] = None
    governance: Optional[GovernanceConfig] = None
    schedule: list[ScheduleEntry] = Field(default_factory=list)
    runtime: RuntimeConfig

    @field_validator("id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z][a-z0-9_-]*$", v):
            raise ValueError(
                f"Agent ID must be lowercase alphanumeric with hyphens/underscores, got: '{v}'"
            )
        return v

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        import re
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            raise ValueError(f"Version must be semver (x.y.z), got: '{v}'")
        return v

    def capability_ids(self) -> set[str]:
        return {cap.id for cap in self.capabilities}
