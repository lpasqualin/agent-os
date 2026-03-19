# Observability Adapter Contract

See `constitution/v0.4.0.md` §6.3.

Captures structured traces from all agent activity including run lifecycle transitions.

## Methods

| Method | Signature | Description |
|--------|----------|-------------|
| trace_start | `(run_id, agent_id, metadata)` | Begin a trace for a run |
| trace_event | `(run_id, event_type, payload)` | Record an event within a trace |
| trace_end | `(run_id, status, failure_reason, metadata)` | Complete trace with final status |
| query | `(filters)` | Query traces. Filters: agent_id, run_id, time_range, status, event_type, failure_reason |
| dashboard_url | `(agent_id)` | Return link to backend dashboard (if applicable) |

## Event Types

| Type | When Emitted |
|------|-------------|
| `state_transition` | Every run lifecycle state change |
| `tool_call` | Before and after every capability execution |
| `memory_op` | Every remember/recall/forget/compact |
| `llm_call` | Every model inference call |
| `governance_decision` | Every policy evaluation result |
| `error` | Any error or exception |

## Invariants

1. Every run lifecycle transition MUST emit a `state_transition` event.
2. Every `trace_end` for a failed run MUST include a `failure_reason` from the failure taxonomy.
3. Traces SHOULD conform to OpenTelemetry-compatible schemas where possible.
4. Raw tool output is captured in traces — this is where it lives, not in memory.
5. Traces MUST be queryable by agent_id, run_id, time_range, and failure_reason at minimum.
