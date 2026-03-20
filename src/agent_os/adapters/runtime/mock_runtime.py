"""Mock runtime adapter — clean reference implementation of the RuntimeAdapter contract.

Returns deterministic, fully-formed RuntimeExecutionResult objects.
Raises UnsupportedCapabilityError for any capability not registered at deploy time.
No I/O, no subprocesses, no latency.
"""

import uuid
from datetime import datetime, timezone

from agent_os.adapters.interfaces import RuntimeAdapter
from agent_os.contracts.errors import UnsupportedCapabilityError
from agent_os.contracts.models import RuntimeExecutionResult, RuntimeStatus


class MockRuntime(RuntimeAdapter):

    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._capability_map: dict[str, str] = {}

    def deploy(self, agent_spec: dict, env_binding: dict | None = None) -> str:
        agent_id = agent_spec.get("id", "unknown")
        self._agents[agent_id] = {
            "spec": agent_spec,
            "state": "deployed",
        }
        # Register all capabilities declared in the spec
        for cap in agent_spec.get("capabilities", []):
            self._capability_map[cap["id"]] = f"mock_tool:{cap['id']}"
        return agent_id

    def start(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            self._agents[agent_id]["state"] = "running"
            return True
        return False

    def stop(self, agent_id: str) -> bool:
        if agent_id in self._agents:
            self._agents[agent_id]["state"] = "stopped"
            return True
        return False

    def status(self, agent_id: str) -> dict:
        if agent_id not in self._agents:
            return {"status": "not_found"}
        return {
            "agent_id": agent_id,
            "state": self._agents[agent_id]["state"],
            "runtime": "mock",
        }

    def execute(self, agent_id: str, capability: str, task: str) -> RuntimeExecutionResult:
        """Return a successful RuntimeExecutionResult for any registered capability.

        Raises:
            UnsupportedCapabilityError: capability not registered at deploy time.
        """
        tool = self._capability_map.get(capability)
        if tool is None:
            raise UnsupportedCapabilityError(
                f"MockRuntime: capability '{capability}' is not registered. "
                f"Was it declared in the agent spec?"
            )

        started_at = datetime.now(timezone.utc)
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        finished_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

        return RuntimeExecutionResult(
            run_id=run_id,
            status=RuntimeStatus.SUCCEEDED,
            capability=capability,
            tool_name=tool,
            output=f"mock result for task: {task}",
            error=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            metadata={"agent_id": agent_id, "runtime": "mock"},
        )

    def resolve_capability(self, capability_id: str) -> str | None:
        return self._capability_map.get(capability_id)

    def health(self) -> dict:
        return {"status": "ok", "runtime": "mock", "agents": len(self._agents)}
