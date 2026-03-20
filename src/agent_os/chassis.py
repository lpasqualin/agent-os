"""Agent OS Chassis — the core boot and execution flow.

This is the central orchestrator. It:
1. Loads and validates an agent spec (structural + semantic)
2. Instantiates adapters from the spec
3. Deploys the agent through the runtime adapter
4. Executes tasks with governance interception and observability tracing
5. Manages run lifecycle state transitions

The chassis owns the mounting points. The adapters are the engines.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_os.contracts.models import (
    AgentSpec,
    CapabilityRegistry,
    Policy,
    ActionClass,
)
from agent_os.loaders.yaml_loader import load_agent_spec, load_registry
from agent_os.validators.schema_validator import validate_schema, ValidationResult
from agent_os.validators.registry_validator import validate_registry
from agent_os.adapters.interfaces import (
    RuntimeAdapter,
    MemoryAdapter,
    ObservabilityAdapter,
    GovernanceAdapter,
)
from agent_os.adapters.runtime.mock_runtime import MockRuntime
from agent_os.adapters.memory.mock_memory import MockMemory
from agent_os.adapters.observability.mock_observability import MockObservability
from agent_os.adapters.governance.mock_governance import MockGovernance


# ── Run States (constitution §5) ──────────────────────────────

VALID_TRANSITIONS = {
    "created":           {"scheduled", "planning", "canceled"},
    "scheduled":         {"planning", "canceled"},
    "planning":          {"awaiting_approval", "executing", "failed"},
    "awaiting_approval": {"executing", "canceled", "failed"},
    "executing":         {"planning", "succeeded", "failed"},
    "succeeded":         set(),  # terminal
    "failed":            {"retrying"},  # or terminal
    "retrying":          {"planning", "failed"},
    "canceled":          set(),  # terminal
}

TERMINAL_STATES = {"succeeded", "failed", "canceled"}


@dataclass
class RunContext:
    """Tracks the state of a single run through the lifecycle."""

    run_id: str
    agent_id: str
    state: str = "created"
    history: list[dict] = field(default_factory=list)

    def transition(self, new_state: str, reason: str = "") -> bool:
        """Transition to a new state. Returns True if valid."""
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            return False
        old_state = self.state
        self.state = new_state
        self.history.append({
            "from": old_state,
            "to": new_state,
            "reason": reason,
        })
        return True


@dataclass
class BootReport:
    """Result of booting an agent through the chassis."""

    agent_id: str
    success: bool
    schema_result: ValidationResult | None = None
    registry_result: ValidationResult | None = None
    adapter_health: dict = field(default_factory=dict)
    capability_mappings: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def print_report(self) -> str:
        lines = []
        lines.append("")
        lines.append("=" * 60)
        if self.success:
            lines.append(f"  BOOT SUCCESS: {self.agent_id}")
        else:
            lines.append(f"  BOOT FAILED: {self.agent_id}")
        lines.append("=" * 60)

        # Schema validation
        lines.append("")
        if self.schema_result:
            status = "PASS" if self.schema_result.passed else "FAIL"
            lines.append(f"  Schema validation:   {status}")
            for err in self.schema_result.errors:
                lines.append(f"    ERROR: {err}")

        # Registry validation
        if self.registry_result:
            status = "PASS" if self.registry_result.passed else "FAIL"
            lines.append(f"  Registry validation: {status}")
            for err in self.registry_result.errors:
                lines.append(f"    ERROR: {err}")
            for warn in self.registry_result.warnings:
                lines.append(f"    WARN:  {warn}")

        # Adapter health
        if self.adapter_health:
            lines.append("")
            lines.append("  Adapter Health:")
            for name, health in self.adapter_health.items():
                status = health.get("status", "unknown")
                lines.append(f"    {name:20s} {status}")

        # Capability mappings
        if self.capability_mappings:
            lines.append("")
            lines.append("  Capability Mappings:")
            for cap_id, tool in sorted(self.capability_mappings.items()):
                marker = "OK" if tool else "UNMAPPED"
                lines.append(f"    {cap_id:25s} -> {tool or '???':30s} [{marker}]")

        # Errors
        if self.errors:
            lines.append("")
            lines.append("  Errors:")
            for err in self.errors:
                lines.append(f"    {err}")

        # Warnings
        if self.warnings:
            lines.append("")
            lines.append("  Warnings:")
            for warn in self.warnings:
                lines.append(f"    {warn}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)


class Chassis:
    """The Agent OS chassis — wires specs to adapters through validated contracts."""

    def __init__(
        self,
        registry_path: str | Path,
    ):
        self.registry_path = Path(registry_path)
        self.registry: CapabilityRegistry | None = None

        # Adapters (set during boot)
        self.runtime: RuntimeAdapter | None = None
        self.memory: MemoryAdapter | None = None
        self.observability: ObservabilityAdapter | None = None
        self.governance: GovernanceAdapter | None = None

        # Loaded spec
        self.spec: AgentSpec | None = None

    def boot(self, spec_path: str | Path) -> BootReport:
        """Boot an agent through the full chassis pipeline.

        1. Load registry
        2. Validate spec (structural)
        3. Validate spec (semantic against registry)
        4. Instantiate adapters
        5. Deploy through runtime
        6. Health check all adapters
        7. Verify capability mappings
        """
        spec_path = Path(spec_path)
        report = BootReport(agent_id="unknown", success=False)

        # ── Step 1: Load registry ──
        try:
            self.registry = load_registry(self.registry_path)
        except Exception as e:
            report.errors.append(f"Failed to load registry: {e}")
            return report

        # ── Step 2: Structural validation (Pass A) ──
        spec, schema_result = validate_schema(spec_path)
        report.schema_result = schema_result

        if not schema_result.passed or spec is None:
            report.errors.append("Schema validation failed — cannot proceed.")
            return report

        self.spec = spec
        report.agent_id = spec.id

        # ── Step 3: Semantic validation (Pass B) ──
        registry_result = validate_registry(spec, self.registry)
        report.registry_result = registry_result

        if not registry_result.passed:
            report.errors.append("Registry validation failed — cannot proceed.")
            return report

        report.warnings.extend(registry_result.warnings)

        # ── Step 4: Check required capability mappings ──
        # (For mock, all capabilities get mapped. For real runtimes, some may be unmapped.)

        # ── Step 5: Instantiate adapters ──
        try:
            self.runtime = MockRuntime()
            self.memory = MockMemory()
            self.observability = MockObservability()
            self.governance = MockGovernance(self.registry, self.spec)
        except Exception as e:
            report.errors.append(f"Adapter initialization failed: {e}")
            return report

        # ── Step 6: Deploy through runtime ──
        try:
            agent_dict = spec.model_dump()
            self.runtime.deploy(agent_dict)
            self.runtime.start(spec.id)
        except Exception as e:
            report.errors.append(f"Runtime deployment failed: {e}")
            return report

        # ── Step 7: Health check ──
        report.adapter_health = {
            "runtime": self.runtime.health(),
            "memory": self.memory.health(),
            "observability": self.observability.health(),
            "governance": self.governance.health(),
        }

        # ── Step 8: Verify capability mappings ──
        unmapped_required = []
        for cap_ref in spec.capabilities:
            tool = self.runtime.resolve_capability(cap_ref.id)
            report.capability_mappings[cap_ref.id] = tool
            if tool is None and cap_ref.required:
                unmapped_required.append(cap_ref.id)

        if unmapped_required:
            report.errors.append(
                f"Required capabilities unmapped: {unmapped_required}"
            )
            return report

        # ── Success ──
        report.success = True
        return report

    def execute_task(self, task: str) -> dict:
        """Execute a task through the full chassis pipeline with governance + tracing.

        This proves the chassis contract works end-to-end:
        - Run lifecycle passes through planning
        - Governance evaluates before execution
        - Observability traces the entire run
        """
        if not self.spec or not self.runtime or not self.governance or not self.observability:
            return {"error": "Chassis not booted. Call boot() first."}

        agent_id = self.spec.id
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        # Create run context
        run = RunContext(run_id=run_id, agent_id=agent_id)

        # Start trace
        self.observability.trace_start(run_id, agent_id, {"task": task})

        # created -> planning (ALWAYS passes through planning)
        run.transition("planning", reason="task_received")
        self.observability.trace_event(run_id, "state_transition", {
            "from": "created", "to": "planning", "reason": "task_received",
        })

        # Planning: determine what capability this task needs
        # (Mock: use first non-pure_read capability as the action)
        action_capability = None
        for cap_ref in self.spec.capabilities:
            cap_def = self.registry.get(cap_ref.id) if self.registry else None
            if cap_def and cap_def.action_class != ActionClass.PURE_READ:
                action_capability = cap_ref.id
                break

        if not action_capability:
            action_capability = self.spec.capabilities[0].id

        # Governance evaluation (Tier 1)
        gov_decision = self.governance.evaluate(agent_id, action_capability, {"task": task})
        self.observability.trace_event(run_id, "governance_decision", {
            "capability": action_capability,
            "decision": gov_decision,
        })
        self.governance.audit_log(agent_id, run_id, action_capability, gov_decision, {"task": task})

        if gov_decision == "deny":
            run.transition("failed", reason="policy_denied")
            self.observability.trace_event(run_id, "state_transition", {
                "from": "planning", "to": "failed", "reason": "policy_denied",
            })
            self.observability.trace_end(run_id, "failed", failure_reason="policy_denied")
            return {
                "run_id": run_id,
                "status": "failed",
                "failure_reason": "policy_denied",
                "lifecycle": run.history,
            }

        if gov_decision == "require_approval":
            run.transition("awaiting_approval", reason="governance_requires_approval")
            self.observability.trace_event(run_id, "state_transition", {
                "from": "planning", "to": "awaiting_approval",
            })

            # Tier 2: request approval (mock auto-approves)
            approval = self.governance.request_approval(agent_id, action_capability, {"task": task})
            self.observability.trace_event(run_id, "approval_result", {"result": approval})

            if approval != "approved":
                run.transition("canceled", reason=f"approval_{approval}")
                self.observability.trace_end(run_id, "canceled", failure_reason=f"approval_{approval}")
                return {
                    "run_id": run_id,
                    "status": "canceled",
                    "failure_reason": f"approval_{approval}",
                    "lifecycle": run.history,
                }

            run.transition("executing", reason="approval_granted")
        else:
            # planning -> executing (allowed)
            run.transition("executing", reason="policy_allowed")

        self.observability.trace_event(run_id, "state_transition", {
            "from": run.history[-1]["from"], "to": "executing",
        })

        # Execute through runtime
        self.observability.trace_event(run_id, "tool_call", {
            "capability": action_capability,
            "tool": self.runtime.resolve_capability(action_capability),
            "task": task,
        })
        runtime_run_id = self.runtime.execute(agent_id, task)

        # Succeeded
        run.transition("succeeded", reason="task_complete")
        self.observability.trace_event(run_id, "state_transition", {
            "from": "executing", "to": "succeeded",
        })
        self.observability.trace_end(run_id, "succeeded", metadata={
            "runtime_run_id": runtime_run_id,
        })

        return {
            "run_id": run_id,
            "status": "succeeded",
            "capability_used": action_capability,
            "lifecycle": run.history,
        }
