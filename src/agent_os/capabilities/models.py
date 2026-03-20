"""Canonical internal models for the capability loader.

These are plain dataclasses — no Pydantic, no magic validation.
The loader fills them; the validator checks them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Capability:
    """A capability as defined in the registry."""

    id: str
    action_class: str
    idempotent: bool
    compensable: Union[bool, str]  # True | False | "na"
    data_sensitivity: str
    justification_required: bool


@dataclass
class AgentCapabilityGrant:
    """A capability reference in an agent spec, with optional policy override."""

    id: str
    policy_override: Optional[str] = None  # "allow" | "confirm" | "deny" | None


@dataclass
class AgentSpec:
    """Minimal agent spec needed for capability validation."""

    agent_id: str
    name: str
    version: str
    capabilities: list[AgentCapabilityGrant] = field(default_factory=list)


@dataclass
class LoadedRegistry:
    """Registry loaded and parsed from disk.

    capabilities is in source order (deterministic given same file).
    """

    capabilities: list[Capability]
    source_file: Optional[str]


@dataclass
class LoadedAgent:
    """Agent spec loaded and parsed from disk."""

    spec: AgentSpec
    source_file: Optional[str]
