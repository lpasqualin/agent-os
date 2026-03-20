"""Mock observability adapter — traces to in-memory log."""

from datetime import datetime, timezone

from agent_os.adapters.interfaces import ObservabilityAdapter


class MockObservability(ObservabilityAdapter):

    def __init__(self):
        self._traces: dict[str, dict] = {}  # run_id -> trace

    def trace_start(self, run_id: str, agent_id: str, metadata: dict | None = None) -> None:
        self._traces[run_id] = {
            "run_id": run_id,
            "agent_id": agent_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "events": [],
            "status": "running",
            "metadata": metadata or {},
        }

    def trace_event(self, run_id: str, event_type: str, payload: dict) -> None:
        if run_id not in self._traces:
            return
        self._traces[run_id]["events"].append({
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        })

    def trace_end(self, run_id: str, status: str, failure_reason: str | None = None, metadata: dict | None = None) -> None:
        if run_id not in self._traces:
            return
        self._traces[run_id]["status"] = status
        self._traces[run_id]["ended_at"] = datetime.now(timezone.utc).isoformat()
        if failure_reason:
            self._traces[run_id]["failure_reason"] = failure_reason
        if metadata:
            self._traces[run_id]["metadata"].update(metadata)

    def query(self, filters: dict) -> list[dict]:
        results = list(self._traces.values())
        if "agent_id" in filters:
            results = [t for t in results if t["agent_id"] == filters["agent_id"]]
        if "status" in filters:
            results = [t for t in results if t["status"] == filters["status"]]
        if "run_id" in filters:
            results = [t for t in results if t["run_id"] == filters["run_id"]]
        return results

    def health(self) -> dict:
        return {"status": "ok", "backend": "mock", "total_traces": len(self._traces)}
