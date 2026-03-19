# Agent OS

**The chassis that owns the mounting points. Not the engines.**

A runtime-agnostic Agent OS chassis that defines contracts between swappable layers: runtime, memory, observability, and governance. Agents are portable artifacts. Parts are interchangeable. Guarantees are sacred.

---

## Current Phase: Phase 1 — Freeze & Define

**Status:** Repo skeleton created. Constitution frozen at v0.4.0.

### Phase 1 Deliverables

1. ~~Repo structure~~ ✅
2. ~~Constitution frozen~~ ✅
3. Capability registry (`capabilities/registry.yaml`)
4. Agent schema (`schema/agent.schema.yaml`)
5. First agent spec: ClawBot (`specs/clawbot.agent.yaml` + `specs/clawbot.env.yaml`)
6. Contract docs (`contracts/*.md`)
7. Mock adapters (runtime, memory, observability, governance)
8. Validation run

### Phase 1 Acceptance Criteria

Phase 1 is **done** when all of the following pass:

- [ ] Agent spec validates against schema (structural validation)
- [ ] Capability IDs validate against registry (semantic validation)
- [ ] Invalid capability IDs fail fast
- [ ] Stricter-than-default policy overrides are accepted
- [ ] More-permissive-than-default policy overrides are rejected
- [ ] Missing required capability mapping fails deployment
- [ ] Memory category law violations are rejected
- [ ] Run lifecycle always passes through `planning` state
- [ ] ClawBot spec deploys through mock runtime adapter
- [ ] Lifecycle trace is produced for a mock run

---

## Architecture

| Layer | Responsibility | Swappable? |
|-------|---------------|------------|
| **Runtime** | Agent execution, tool dispatch, scheduling, channel I/O | Yes — behind RuntimeAdapter |
| **Memory** | Persistent agent state, cross-session context, knowledge | Yes — behind MemoryAdapter |
| **Observability** | Tracing, metrics, evals, debugging | Yes — behind ObsAdapter |
| **Governance** | Policy enforcement, approval gates, audit, spend limits | Partially — core to chassis |
| **Agent Spec** | Declarative agent definitions, portable across runtimes | N/A — this IS the chassis |

### Core Principles

1. Own the contracts, not the engines
2. Every layer is swappable while operational
3. Agents are portable artifacts
4. Governance is not optional
5. Observe everything, surface nothing by default
6. No premature scaling
7. Agents define intent, runs are the operational unit
8. Define guarantees, not mechanisms

See `constitution/v0.4.0.md` for the full architecture constitution.

---

## Repo Structure

```
agent-os/
├── constitution/       # Frozen architecture constitution
├── contracts/          # Adapter interface contracts
├── schema/             # Agent spec schema (structural validation)
├── capabilities/       # Capability registry (semantic validation)
├── specs/              # Agent definitions + env bindings
├── identity/           # Agent identity files (SOUL.md, USER.md)
├── adapters/           # Adapter implementations
│   ├── runtime/        # mock/, openclaw/
│   ├── memory/         # mock/
│   ├── observability/  # mock/
│   └── governance/     # mock/
└── tests/              # Fixtures and phase validation
```

---

## What We Do NOT Build

- A memory engine (Mem0, Zep exist — we build MemoryAdapter)
- An observability platform (Laminar, Langfuse exist — we build ObsAdapter)
- A new LLM runtime (OpenClaw, OpenFang exist — we build RuntimeAdapter)
- A workflow framework (LangGraph, CrewAI exist — we adopt if needed)
- A model router, channel system, or tool marketplace

---

*Leo Pasqua — March 18, 2026*
*With architectural review by Ax*
