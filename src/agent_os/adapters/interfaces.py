"""Adapter interfaces — the contracts that all backends must implement.

These are abstract base classes. The chassis programs against these interfaces.
Backends (mock, OpenClaw, Mem0, Laminar, etc.) implement them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_os.contracts.models import RuntimeExecutionResult


class RuntimeAdapter(ABC):
    """Runtime adapter contract — see contracts/runtime.md."""

    @abstractmethod
    def deploy(self, agent_spec: dict, env_binding: dict | None = None) -> str:
        """Deploy an agent from spec. Returns agent_id."""
        ...

    @abstractmethod
    def start(self, agent_id: str) -> bool:
        ...

    @abstractmethod
    def stop(self, agent_id: str) -> bool:
        ...

    @abstractmethod
    def status(self, agent_id: str) -> dict:
        """Returns health, run state, metadata."""
        ...

    @abstractmethod
    def execute(self, agent_id: str, capability: str, task: str) -> "RuntimeExecutionResult":
        """Run a one-shot task for a specific capability.

        Returns a fully normalised RuntimeExecutionResult on success.

        Raises:
            UnsupportedCapabilityError: capability is not in this adapter's scope.
            RuntimeInvocationError:     runtime call failed (non-zero exit, etc.).
            RuntimeTimeoutError:        invocation exceeded the configured timeout.
            RuntimeContractError:       raw output could not be normalised.
        """
        ...

    @abstractmethod
    def resolve_capability(self, capability_id: str) -> str | None:
        """Map capability to runtime-native tool name.

        Returns the tool name string if supported.
        May return None (permissive adapters) or raise ValueError /
        UnsupportedCapabilityError (strict adapters) for unknown capabilities.
        """
        ...

    @abstractmethod
    def health(self) -> dict:
        ...


class MemoryAdapter(ABC):
    """Memory adapter contract — see contracts/memory.md."""

    @abstractmethod
    def remember(self, agent_id: str, entry: dict) -> str:
        """Store a memory entry. Returns entry_id."""
        ...

    @abstractmethod
    def recall(self, agent_id: str, query: str, filters: dict | None = None) -> list[dict]:
        """Semantic search over agent memory."""
        ...

    @abstractmethod
    def forget(self, agent_id: str, selector: dict) -> int:
        """Remove entries matching selector. Returns count removed."""
        ...

    @abstractmethod
    def list_entries(self, agent_id: str, filters: dict | None = None) -> list[dict]:
        """Structured query (no semantic matching)."""
        ...

    @abstractmethod
    def compact(self, agent_id: str) -> dict:
        """Trigger compaction. Returns summary of actions taken."""
        ...

    @abstractmethod
    def export(self, agent_id: str, fmt: str = "json") -> str:
        """Export all memory as structured data."""
        ...

    @abstractmethod
    def health(self) -> dict:
        ...


class ObservabilityAdapter(ABC):
    """Observability adapter contract — see contracts/observability.md."""

    @abstractmethod
    def trace_start(self, run_id: str, agent_id: str, metadata: dict | None = None) -> None:
        ...

    @abstractmethod
    def trace_event(self, run_id: str, event_type: str, payload: dict) -> None:
        ...

    @abstractmethod
    def trace_end(self, run_id: str, status: str, failure_reason: str | None = None, metadata: dict | None = None) -> None:
        ...

    @abstractmethod
    def query(self, filters: dict) -> list[dict]:
        ...

    @abstractmethod
    def health(self) -> dict:
        ...


class GovernanceAdapter(ABC):
    """Governance adapter contract — see contracts/governance.md."""

    @abstractmethod
    def evaluate(self, agent_id: str, action: str, context: dict | None = None) -> str:
        """Returns 'allow', 'deny', or 'require_approval'."""
        ...

    @abstractmethod
    def request_approval(self, agent_id: str, action: str, context: dict | None = None) -> str:
        """Returns 'approved', 'denied', or 'timeout'."""
        ...

    @abstractmethod
    def audit_log(self, agent_id: str, run_id: str, action: str, result: str, metadata: dict | None = None) -> None:
        """Append-only audit record."""
        ...

    @abstractmethod
    def check_budget(self, agent_id: str) -> dict:
        """Returns remaining budget for current period."""
        ...

    @abstractmethod
    def health(self) -> dict:
        ...
