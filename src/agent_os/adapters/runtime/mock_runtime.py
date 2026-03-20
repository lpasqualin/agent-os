"""Mock runtime adapter — returns deterministic fake responses."""

import uuid
from agent_os.adapters.interfaces import RuntimeAdapter


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
        # Build capability map (mock just echoes capability IDs)
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

    def execute(self, agent_id: str, task: str) -> str:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        return run_id

    def resolve_capability(self, capability_id: str) -> str | None:
        return self._capability_map.get(capability_id)

    def health(self) -> dict:
        return {"status": "ok", "runtime": "mock", "agents": len(self._agents)}
