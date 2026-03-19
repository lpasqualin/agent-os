# Runtime Adapter Contract

See `constitution/v0.4.0.md` §6.1 for full specification.

## Methods

- `deploy(agent_spec, env_binding)` → Resolve, map capabilities, deploy
- `start(agent_id)` → Start agent
- `stop(agent_id)` → Stop gracefully
- `status(agent_id)` → Health, run state, metadata
- `list()` → All agents with state
- `execute(agent_id, task)` → One-shot task, returns run_id
- `resolve_capability(capability_id)` → Runtime-native tool

## Compliance Levels

- **L1:** Spec-compatible (parses + deploys)
- **L2:** Semantically-compatible (behavior preserved)
- **L3:** Operationally-verified (test suite passed)

## TODO

- Phase 1: Define mock implementation
- Phase 2A: Define OpenClaw implementation
