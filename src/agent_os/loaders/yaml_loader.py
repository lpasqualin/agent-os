"""YAML loader for agent specs and capability registries."""

from pathlib import Path

import yaml

from agent_os.contracts.models import AgentSpec, CapabilityRegistry


def load_agent_spec(path: str | Path) -> AgentSpec:
    """Load and parse an agent spec from YAML."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Agent spec not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"Agent spec is empty: {path}")

    return AgentSpec(**raw)


def load_registry(path: str | Path) -> CapabilityRegistry:
    """Load and parse the capability registry from YAML."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Capability registry not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if raw is None or "capabilities" not in raw:
        raise ValueError(f"Capability registry is empty or malformed: {path}")

    return CapabilityRegistry(**raw)
