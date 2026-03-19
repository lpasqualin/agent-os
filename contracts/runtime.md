# Runtime Adapter Contract

See `constitution/v0.4.0.md` §6.1.

Translates agent specs into running agents. Owns the capability map and config resolution.

## Methods

| Method | Signature | Description |
|--------|----------|-------------|
| deploy | `(agent_spec, env_binding)` | Resolve config, map capabilities to native tools, deploy agent |
| start | `(agent_id)` | Start a deployed agent |
| stop | `(agent_id)` | Stop gracefully |
| status | `(agent_id)` | Return health, current run state, runtime metadata |
| list | `()` | All deployed agents with current state |
| execute | `(agent_id, task)` | Run one-shot task, return run_id |
| resolve_capability | `(capability_id)` | Return runtime-native tool/skill for a capability |

## Responsibilities

1. **Config resolution:** Merges portable spec + env binding into resolved deployment (ephemeral, never persisted).
2. **Capability mapping:** Translates `domain.verb` capabilities into runtime-native tools. Mapping is owned by the adapter, not the spec.
3. **Lifecycle management:** Starts, stops, monitors agents. Reports run state per lifecycle contract.
4. **Channel wiring:** Connects declared channel bindings to actual messaging adapters.
5. **Schedule execution:** Triggers cron-defined tasks at specified times.

## Compliance Levels

| Level | Name | Meaning |
|-------|------|---------|
| L1 | Spec-compatible | Parses agent.yaml, maps capabilities, agent starts and runs |
| L2 | Semantically-compatible | Capability behavior preserved across runtimes. All adapter contracts honored. |
| L3 | Operationally-verified | Passed test suite: behavior, governance, failures, audit, performance |

## Invariants

1. Deploy MUST fail if a required capability has no mapping.
2. Deploy MUST validate capability IDs against the registry.
3. Deploy MUST reject policy overrides more permissive than action class defaults.
4. The runtime MUST NOT store resolved deployment config to disk.
5. The runtime MUST report run state transitions to the observability adapter.
