# Observability Adapter Contract

See `constitution/v0.4.0.md` §6.3 for full specification.

## Methods

- `trace_start(run_id, agent_id, metadata)` → Begin trace
- `trace_event(run_id, event_type, payload)` → Record event
- `trace_end(run_id, status, failure_reason, metadata)` → Complete trace
- `query(filters)` → Query historical traces
- `dashboard_url(agent_id)` → Link to backend dashboard

## Event Types

tool_call, memory_op, llm_call, state_transition, governance_decision, error

## TODO

- Phase 1: Define mock implementation
- Phase 2B: Evaluate Laminar vs Langfuse vs Phoenix
