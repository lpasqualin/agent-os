"""Mock memory adapter — in-memory dict with category law enforcement."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from agent_os.adapters.interfaces import MemoryAdapter

# Category durability defaults (from constitution §6.2.2)
CATEGORY_TTL = {
    "fact": None,        # durable
    "preference": None,  # durable
    "event": 30,         # days
    "decision": None,    # durable
    "learning": None,    # durable
    "context": 1,        # days (24h)
}

VALID_CATEGORIES = set(CATEGORY_TTL.keys())
VALID_SOURCES = {"user_stated", "inferred", "tool_output", "system"}
VALID_SCOPES = {"agent", "shared", "global"}


class MockMemory(MemoryAdapter):

    def __init__(self):
        self._store: dict[str, list[dict]] = {}  # agent_id -> entries

    def remember(self, agent_id: str, entry: dict) -> str:
        # Validate category
        category = entry.get("category")
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid memory category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        # Validate scope
        scope = entry.get("scope", "agent")
        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid memory scope '{scope}'. Must be one of: {sorted(VALID_SCOPES)}")

        # Validate source
        source = entry.get("source", "inferred")
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid memory source '{source}'. Must be one of: {sorted(VALID_SOURCES)}")

        # HARD LAW: tool_output must not become raw memory
        if source == "tool_output" and category not in ("fact", "decision", "learning"):
            raise ValueError(
                f"tool_output source can only produce fact/decision/learning categories, "
                f"not '{category}'. Raw tool output must be summarized."
            )

        # Generate entry
        entry_id = f"mem_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)

        record = {
            "id": entry_id,
            "category": category,
            "content": entry.get("content", ""),
            "scope": scope,
            "confidence": entry.get("confidence", 1.0),
            "source": source,
            "supersedes": entry.get("supersedes"),
            "created_at": now.isoformat(),
            "expires_at": None,
        }

        # Apply default TTL based on category
        ttl_days = CATEGORY_TTL.get(category)
        if ttl_days is not None and "expires_at" not in entry:
            record["expires_at"] = (now + timedelta(days=ttl_days)).isoformat()
        elif "expires_at" in entry:
            record["expires_at"] = entry["expires_at"]

        if agent_id not in self._store:
            self._store[agent_id] = []
        self._store[agent_id].append(record)

        return entry_id

    def recall(self, agent_id: str, query: str, filters: dict | None = None) -> list[dict]:
        # Mock: simple substring match (real backend would do semantic search)
        entries = self._store.get(agent_id, [])
        results = [e for e in entries if query.lower() in e["content"].lower()]
        if filters:
            if "category" in filters:
                results = [e for e in results if e["category"] == filters["category"]]
            if "scope" in filters:
                results = [e for e in results if e["scope"] == filters["scope"]]
        return results

    def forget(self, agent_id: str, selector: dict) -> int:
        entries = self._store.get(agent_id, [])
        before = len(entries)
        if "id" in selector:
            entries = [e for e in entries if e["id"] != selector["id"]]
        if "category" in selector:
            entries = [e for e in entries if e["category"] != selector["category"]]
        self._store[agent_id] = entries
        return before - len(entries)

    def list_entries(self, agent_id: str, filters: dict | None = None) -> list[dict]:
        entries = self._store.get(agent_id, [])
        if filters:
            if "category" in filters:
                entries = [e for e in entries if e["category"] == filters["category"]]
            if "scope" in filters:
                entries = [e for e in entries if e["scope"] == filters["scope"]]
        return entries

    def compact(self, agent_id: str) -> dict:
        entries = self._store.get(agent_id, [])
        now = datetime.now(timezone.utc)
        before = len(entries)
        # Prune expired entries
        entries = [
            e for e in entries
            if e["expires_at"] is None
            or datetime.fromisoformat(e["expires_at"]) > now
        ]
        self._store[agent_id] = entries
        return {"pruned": before - len(entries), "remaining": len(entries)}

    def export(self, agent_id: str, fmt: str = "json") -> str:
        entries = self._store.get(agent_id, [])
        return json.dumps(entries, indent=2)

    def health(self) -> dict:
        total = sum(len(v) for v in self._store.values())
        return {"status": "ok", "backend": "mock", "total_entries": total}
