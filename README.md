# Agent OS

**The chassis that owns the mounting points. Not the engines.**

A runtime-agnostic Agent OS chassis that defines contracts between swappable layers: runtime, memory, observability, and governance. Agents are portable artifacts. Parts are interchangeable. Guarantees are sacred.

---

## Current Status

**Foundation complete (428 tests passing). Next: A0 — Refactor legacy model/retry spec into current phases.**

| Item | State |
|------|-------|
| Constitution | v0.4.0 — FROZEN |
| Roadmap | v3.2 — LOCKED |
| Schema, registry, agent spec | ✅ Complete |
| Contract docs | ✅ Complete |
| Mock adapters (runtime, memory, obs, governance) | ✅ Complete |
| OpenClawRuntime | ⚠️ Partial — 3 capabilities, sandbox not configured |
| Journal | ❌ Flat directory, no partitioning, no hash chain |
| Core loop | ❌ All mock — no real policy, no real runtime, no tamper-evident journal |

---

## Core Principle (v3.2)

**Agent OS does not own execution truth. It owns audit truth.**

```
Runtime = execution truth   (OpenClaw — not controlled by Agent OS)
Journal  = audit truth      (normalized, tamper-evident, independently verifiable)
```

Adapters bridge the two. The journal stores only normalized RunRecords.

---

## Build Sequence

```
A0 → A1 → A2 (A2a, A2b) → A3
  → B1 (B1a, B1b, B1c) → B2
  → D1 → D2 (D2a, D2b, D2c)
  → ⬛ CORE LOOP PROOF GATE
  → D3 → C1 → C2 → E1 → E2 → F1 → F2 → G1 → G2 → H1 → H2
```

See `ROADMAP.md` for full phase specs. See `EXECUTION.md` for per-phase checklists.

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
├── constitution/       # Frozen architecture constitution (v0.4.0)
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
├── tests/              # Fixtures and phase validation
├── ROADMAP.md          # Build roadmap v3.2
└── EXECUTION.md        # Per-phase execution checklists
```

---

## What We Do NOT Build

- A memory engine (Mem0, Zep exist — we build MemoryAdapter)
- An observability platform (Laminar, Langfuse exist — we build ObsAdapter)
- A new LLM runtime (OpenClaw, OpenFang exist — we build RuntimeAdapter)
- A workflow framework (LangGraph, CrewAI exist — we adopt if needed)
- A model router, channel system, or tool marketplace

---

*Leo Pasqua — April 2026*
*With architectural review by Ax*
