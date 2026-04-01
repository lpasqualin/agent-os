# Agent OS

**The chassis that owns the mounting points. Not the engines.**

A runtime-agnostic Agent OS chassis that defines contracts between swappable layers: runtime, memory, observability, and governance. Agents are portable artifacts. Parts are interchangeable. Guarantees are sacred.

---

## What Is This?

Agent OS is an architectural chassis for governed AI agents. It defines the contracts between the layers that agents depend on — runtime, memory, observability, governance — without implementing any of them. The goal: agents are portable specs that can run on any compliant runtime.

## Why Does It Exist?

Most agent frameworks conflate execution substrate with agent identity. This creates agents that can't be moved, runtimes that can't be swapped, and governance bolted on as an afterthought. Agent OS treats the architecture differently:

- The agent spec is the portable artifact
- The adapter layer is the seam between the spec and the implementation
- Governance is a hard structural requirement, not optional middleware
- The chassis defines guarantees; adapters choose mechanisms

## What Makes It Interesting?

- **Formal architecture constitution** — 8 immutable principles, frozen at v0.4.0, not reopened unless implementation exposes a structural flaw
- **Action taxonomy** — every side-effecting action is classified (pure_read through privileged_control), and governance defaults derive from the class
- **Adapter-first design** — runtime, memory, observability, and governance are all behind adapter interfaces; backends are swappable without touching agent specs
- **423 tests across 9 sealed phases** — from capability validation through operator introspection, replay, and failure analysis
- **Real agent integration** — the ClawBot agent spec is the first agent defined against this chassis and runs against the OpenClaw runtime adapter

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

## Current State

**Phases completed:** 1 through 5A (sealed). 423 tests passing.

| Phase | Deliverable |
|-------|------------|
| Phase 1 | Constitution, capability registry, agent schema, ClawBot spec, mock adapters |
| Phase 2A | Capability validation, sandbox isolation, fallback logic |
| Phase 2B | Runtime contract hardening, structured error surface |
| Phase 2C | Durable execution journal |
| Phase 3A | Sandbox runtime execution, `agent-os run` CLI |
| Phase 3B | Operator introspection commands (`runs`, `journal latest`, `inspect`) |
| Phase 3C | Governed replay |
| Phase 4A | Filtered run queries, operator summary view |
| Phase 4B | Operator shortcuts (`--latest`, `--last-failure`) |
| Phase 4C | Failure analysis surfacing in inspect output |
| Phase 5A | Capability pack loader, validator, and CLI commands |

## Repo Structure

```
agent-os/
├── constitution/       # Frozen architecture constitution (v0.4.0)
├── contracts/          # Adapter interface contracts
├── schema/             # Agent spec schema (structural validation)
├── capabilities/       # Capability registry (semantic validation)
├── specs/              # Agent definitions (ClawBot, sandbox variant)
├── identity/           # Agent identity files (SOUL.md, USER.md)
├── adapters/           # Adapter implementations
│   ├── runtime/        # mock/, openclaw/
│   ├── memory/         # mock/
│   ├── observability/  # mock/
│   └── governance/     # mock/
└── tests/              # Phase-sealed test suites (phases 1–5A)
```

Start at `constitution/v0.4.0.md` for the full architecture contract.
Then read `specs/clawbot.agent.yaml` to see an agent defined against it.
Then run the tests: `pytest tests/`.

## What This Does NOT Build

- A memory engine (Mem0, Zep exist — we build MemoryAdapter)
- An observability platform (Laminar, Langfuse exist — we build ObsAdapter)
- A new LLM runtime (OpenClaw, OpenFang exist — we build RuntimeAdapter)
- A workflow framework (LangGraph, CrewAI exist — we adopt if needed)
- A model router, channel system, or tool marketplace

---

*LP — March 18, 2026*
*With architectural review by Ax*
