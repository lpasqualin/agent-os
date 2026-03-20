"""OpenClaw runtime adapter — Phase 2A sandbox implementation.

Connects Agent OS to a sandboxed OpenClaw instance via one-shot CLI invocation
(``openclaw agent --local --json``). No gateway required; no always-on service.
Runs as the invoking user (leo-paz) — no sudo.

Design decisions:
- ``resolve_capability`` has an explicit, narrow map. Unsupported capabilities
  raise ValueError — there is no silent pass-through. This enforces the
  capability mapping law: an adapter may only claim capabilities it actually
  implements.
- ``invoke_fn`` injection replaces the real subprocess in tests. No I/O,
  no API keys, no live OpenClaw needed for the test suite.
- ``execute()`` is error-proof: subprocess/JSON failures are caught and stored
  internally so the chassis lifecycle is never interrupted by sandbox errors.
- ``health()`` always returns ok — the sandbox is stateless and on-demand.

Real invocation (no sudo, runs as leo-paz):
    OPENCLAW_CONFIG_PATH=~/openclaw-sandbox/config/openclaw.json \\
    OPENCLAW_STATE_DIR=~/openclaw-sandbox/state \\
    /home/clawbot/.npm-global/bin/openclaw agent --local --json --message "..."

Binary access: /home/clawbot/.npm-global/bin/openclaw is world-executable (777)
and /home/clawbot is traversable (o+x). Leo-paz can call it directly.

For live invocations, TAVILY_WEB_SEARCH_KEY and TODOIST_API_KEY must be
exported by the caller (sourced from /etc/openclaw.env or equivalent).
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Callable

from agent_os.adapters.interfaces import RuntimeAdapter

# ── Constants ─────────────────────────────────────────────────

_DEFAULT_SANDBOX_ROOT = Path.home() / "openclaw-sandbox"
_OPENCLAW_BIN = "/home/clawbot/.npm-global/bin/openclaw"

# Phase 2A explicit capability → OpenClaw skill mappings.
# This map is the complete scope of this adapter. Anything not listed here
# is not supported and resolve_capability will raise — no silent fallback.
_CAPABILITY_MAP: dict[str, str] = {
    "tasks.read":    "todoist",        # Todoist skill — read-only task list
    "web.search":    "tavily",         # Tavily skill — stateless web search
    "memory.recall": "openclaw_memory", # OpenClaw built-in memory search
}


# ── Adapter ───────────────────────────────────────────────────

class OpenClawRuntime(RuntimeAdapter):
    """RuntimeAdapter backed by a sandboxed OpenClaw instance.

    Phase 2A scope: tasks.read, web.search, memory.recall.
    All other capabilities are explicitly unsupported — resolve_capability
    raises ValueError for anything outside this set.

    Args:
        sandbox_root: Root of the openclaw-sandbox tree. Defaults to
                      ``~/openclaw-sandbox``. Must contain
                      ``config/openclaw.json`` for real invocations.
        binary:       Absolute path to the openclaw binary. Must be
                      executable by the invoking user without sudo.
        invoke_fn:    Optional ``callable(message: str) -> dict``. When set,
                      replaces the real subprocess call. Use in tests to mock
                      the invocation boundary with no I/O.
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
        """Invoke OpenClaw and return a normalized result dict.

        Uses ``invoke_fn`` if injected (tests). Otherwise runs the real
        subprocess as the current user — no sudo. All errors are caught and
        returned as ``{"status": "error", "error": "<reason>"}``.
        """
        if self._invoke_fn is not None:
            try:
                return self._invoke_fn(message)
            except Exception as exc:
                return {"status": "error", "error": str(exc)}

        # ── Real subprocess path (runs as leo-paz, no sudo) ───
        config_path = self._config_path()
        if not config_path.exists():
            return {
                "status": "error",
                "error": f"Sandbox config not found: {config_path}",
            }

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
            "OPENCLAW_STATE_DIR": str(self._state_dir()),
        }

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
            )
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "error": proc.stderr.strip() or "non-zero exit",
                    "exit_code": proc.returncode,
                }
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "timeout", "timeout_seconds": self._timeout}
        except json.JSONDecodeError as exc:
            return {"status": "error", "error": f"json_decode: {exc}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

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
        """Mark agent stopped."""
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
            "runtime": "openclaw",
            "mode": "sandbox",
            "sandbox_root": str(self.sandbox_root),
        }

    def execute(self, agent_id: str, task: str) -> str:
        """Invoke sandbox OpenClaw for a one-shot task. Returns run_id.

        Sandbox errors are captured and stored; this method never raises.
        Use ``get_run_result(agent_id, run_id)`` to inspect the result.
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        result = self._invoke(task)
        if agent_id in self._agents:
            self._agents[agent_id]["runs"][run_id] = {
                "task": task,
                "result": result,
            }
        return run_id

    def get_run_result(self, agent_id: str, run_id: str) -> dict | None:
        """Return the stored invocation result for a run.

        Not part of the RuntimeAdapter interface contract. Used by Phase 2A
        tests to assert on what OpenClaw actually returned.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        return agent["runs"].get(run_id)

    def resolve_capability(self, capability_id: str) -> str | None:
        """Map capability ID to the OpenClaw skill that handles it.

        Phase 2A supported capabilities:
            tasks.read    → todoist
            web.search    → tavily
            memory.recall → openclaw_memory

        Any capability not in this explicit set raises ValueError. This adapter
        has a narrow, declared scope — no silent pass-through.

        Raises:
            ValueError: if capability_id is not in the Phase 2A support set.
        """
        if capability_id in _CAPABILITY_MAP:
            return _CAPABILITY_MAP[capability_id]
        raise ValueError(
            f"OpenClawRuntime: capability '{capability_id}' is not supported by this adapter. "
            f"Supported capabilities: {sorted(_CAPABILITY_MAP)}"
        )

    def health(self) -> dict:
        """Health check — always ok. Sandbox is stateless; config existence noted."""
        return {
            "status": "ok",
            "runtime": "openclaw",
            "mode": "sandbox",
            "sandbox_root": str(self.sandbox_root),
            "config_exists": self._config_path().exists(),
            "binary": self.binary,
        }
