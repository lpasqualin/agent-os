"""OpenClaw runtime adapter — Phase 2B hardened implementation.

Connects Agent OS to a sandboxed OpenClaw instance via one-shot CLI invocation
(``openclaw agent --local --json``). No gateway required; no always-on service.
Runs as the invoking user (leo-paz) — no sudo.

Phase 2B contract:
- execute() returns RuntimeExecutionResult on success.
- execute() raises structured errors on failure — no silent swallowing.
- _invoke() surfaces subprocess/JSON failures as typed exceptions.
- _normalize() converts raw OpenClaw output to RuntimeExecutionResult or raises
  RuntimeContractError if the shape is unrecognisable.

Supported capabilities (Phase 2A scope, unchanged):
    tasks.read    → todoist
    web.search    → tavily
    memory.recall → openclaw_memory

Anything outside this set raises UnsupportedCapabilityError.

Binary access:
    /home/clawbot/.npm-global/bin/openclaw is world-executable (777).
    /home/clawbot is traversable (o+x). Leo-paz invokes it directly.

For live invocations, TAVILY_WEB_SEARCH_KEY and TODOIST_API_KEY must be
exported in the caller's environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from agent_os.adapters.interfaces import RuntimeAdapter
from agent_os.contracts.errors import (
    UnsupportedCapabilityError,
    RuntimeInvocationError,
    RuntimeTimeoutError,
    RuntimeContractError,
)
from agent_os.contracts.models import RuntimeExecutionResult, RuntimeStatus

# ── Constants ─────────────────────────────────────────────────

_DEFAULT_SANDBOX_ROOT = Path.home() / "openclaw-sandbox"
_OPENCLAW_BIN = "/home/clawbot/.npm-global/bin/openclaw"

# Phase 2A explicit capability → OpenClaw skill mappings.
# Anything not listed here is not supported — no generic fallback.
_CAPABILITY_MAP: dict[str, str] = {
    "tasks.read":    "todoist",
    "web.search":    "tavily",
    "memory.recall": "openclaw_memory",
}


# ── Adapter ───────────────────────────────────────────────────

class OpenClawRuntime(RuntimeAdapter):
    """RuntimeAdapter backed by a sandboxed OpenClaw instance.

    Phase 2A capability scope: tasks.read, web.search, memory.recall.

    Args:
        sandbox_root: Root of the openclaw-sandbox tree. Defaults to
                      ``~/openclaw-sandbox``. Must contain
                      ``config/openclaw.json`` for real invocations.
        binary:       Absolute path to the openclaw binary. Must be
                      executable by the invoking user without sudo.
        invoke_fn:    Optional ``callable(message: str) -> dict``. When set,
                      replaces the real subprocess call. Use in tests to mock
                      the invocation boundary without any I/O.
        timeout:      Subprocess timeout in seconds. Default 30.
    """

    def __init__(
        self,
        sandbox_root: str | Path | None = None,
        binary: str = _OPENCLAW_BIN,
        invoke_fn: Callable[[str], dict] | None = None,
        timeout: int = 30,
    ):
        self.sandbox_root = Path(sandbox_root or _DEFAULT_SANDBOX_ROOT)
        self.binary = binary
        self._invoke_fn = invoke_fn
        self._timeout = timeout
        self._agents: dict[str, dict] = {}

    # ── Private helpers ───────────────────────────────────────

    def _config_path(self) -> Path:
        return self.sandbox_root / "config" / "openclaw.json"

    def _state_dir(self) -> Path:
        return self.sandbox_root / "state"

    def _invoke(self, message: str) -> dict:
        """Call OpenClaw and return the raw response dict.

        Uses ``invoke_fn`` if injected (tests). Otherwise runs the real
        subprocess as the current user — no sudo.

        Raises:
            RuntimeInvocationError: subprocess failed or invoke_fn raised.
            RuntimeTimeoutError:    subprocess exceeded self._timeout.
            RuntimeContractError:   stdout was not valid JSON.
        """
        if self._invoke_fn is not None:
            try:
                return self._invoke_fn(message)
            except Exception as exc:
                raise RuntimeInvocationError(
                    f"invoke_fn raised: {exc}"
                ) from exc

        # ── Real subprocess (runs as leo-paz, no sudo) ────────
        config_path = self._config_path()
        if not config_path.exists():
            raise RuntimeInvocationError(
                f"Sandbox config not found: {config_path}"
            )

        cmd = [
            self.binary,
            "agent",
            "--local",
            "--json",
            "--message", message,
        ]
        env = {
            **os.environ,
            "OPENCLAW_CONFIG_PATH": str(config_path),
            "OPENCLAW_STATE_DIR":   str(self._state_dir()),
        }

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeTimeoutError(
                f"OpenClaw timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:
            raise RuntimeInvocationError(f"Subprocess failed: {exc}") from exc

        if proc.returncode != 0:
            raise RuntimeInvocationError(
                f"OpenClaw exit {proc.returncode}: "
                f"{proc.stderr.strip() or '(no stderr)'}"
            )

        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeContractError(
                f"OpenClaw returned non-JSON output: {exc}"
            ) from exc

    def _normalize(
        self,
        raw: dict,
        run_id: str,
        capability: str,
        tool_name: str,
        agent_id: str,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: int,
    ) -> RuntimeExecutionResult:
        """Normalize raw OpenClaw output to RuntimeExecutionResult.

        Raises:
            RuntimeContractError: if raw is not a dict.
        """
        if not isinstance(raw, dict):
            raise RuntimeContractError(
                f"Expected dict from OpenClaw, got {type(raw).__name__}"
            )

        raw_status = raw.get("status", "ok")

        if raw_status == "error":
            return RuntimeExecutionResult(
                run_id=run_id,
                status=RuntimeStatus.FAILED,
                capability=capability,
                tool_name=tool_name,
                output=None,
                error=raw.get("error") or str(raw),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                raw_response=raw,
                metadata={"agent_id": agent_id},
            )

        # Extract output from known response keys
        output = raw.get("reply") or raw.get("output") or raw.get("content")
        return RuntimeExecutionResult(
            run_id=run_id,
            status=RuntimeStatus.SUCCEEDED,
            capability=capability,
            tool_name=tool_name,
            output=str(output) if output is not None else None,
            error=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            raw_response=raw,
            metadata={"agent_id": agent_id},
        )

    # ── RuntimeAdapter contract ───────────────────────────────

    def deploy(self, agent_spec: dict, env_binding: dict | None = None) -> str:
        """Register agent from spec. No remote call — sandbox is on-demand."""
        agent_id = agent_spec.get("id", "unknown")
        self._agents[agent_id] = {
            "spec": agent_spec,
            "state": "deployed",
            "runs": {},
        }
        return agent_id

    def start(self, agent_id: str) -> bool:
        """Mark agent running. No daemon to start — sandbox is invoked on execute()."""
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
            "state":    self._agents[agent_id]["state"],
            "runtime":  "openclaw",
            "mode":     "sandbox",
            "sandbox_root": str(self.sandbox_root),
        }

    def execute(
        self, agent_id: str, capability: str, task: str
    ) -> RuntimeExecutionResult:
        """Invoke sandbox OpenClaw for a one-shot task.

        Raises:
            UnsupportedCapabilityError: capability not in Phase 2A scope.
            RuntimeInvocationError:     subprocess/invoke_fn failed.
            RuntimeTimeoutError:        invocation timed out.
            RuntimeContractError:       raw output not normalisable.
        """
        # 1. Validate capability (strict — no fallback)
        try:
            tool_name = self.resolve_capability(capability)
        except ValueError as exc:
            raise UnsupportedCapabilityError(str(exc)) from exc

        started_at = datetime.now(timezone.utc)
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        # 2. Invoke (raises on timeout/invocation/JSON error)
        raw = self._invoke(task)

        finished_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))

        # 3. Normalize (raises RuntimeContractError if raw is malformed)
        result = self._normalize(
            raw, run_id, capability, tool_name, agent_id,
            started_at, finished_at, duration_ms,
        )

        # 4. Store for introspection
        if agent_id in self._agents:
            self._agents[agent_id]["runs"][run_id] = {
                "task":             task,
                "result":           raw,        # raw dict (preserved for compat)
                "execution_result": result,     # Phase 2B: typed result
            }

        return result

    def get_run_result(self, agent_id: str, run_id: str) -> dict | None:
        """Return the stored run entry for introspection in tests.

        Entry keys:
            task             – original task string
            result           – raw dict from invoke_fn / subprocess
            execution_result – RuntimeExecutionResult (Phase 2B)
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        return agent["runs"].get(run_id)

    def resolve_capability(self, capability_id: str) -> str | None:
        """Map capability ID to OpenClaw skill name.

        Phase 2A supported capabilities:
            tasks.read    → todoist
            web.search    → tavily
            memory.recall → openclaw_memory

        Raises:
            ValueError: for any capability outside this set.
        """
        if capability_id in _CAPABILITY_MAP:
            return _CAPABILITY_MAP[capability_id]
        raise ValueError(
            f"OpenClawRuntime: capability '{capability_id}' is not supported. "
            f"Supported: {sorted(_CAPABILITY_MAP)}"
        )

    def health(self) -> dict:
        return {
            "status":        "ok",
            "runtime":       "openclaw",
            "mode":          "sandbox",
            "sandbox_root":  str(self.sandbox_root),
            "config_exists": self._config_path().exists(),
            "binary":        self.binary,
        }
