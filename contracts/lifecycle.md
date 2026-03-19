# Run Lifecycle Contract

See `constitution/v0.4.0.md` §5.

The run is the operational unit. Agent specs define intent; runs are what the system manages.

## State Machine

```
created → scheduled → planning → awaiting_approval → executing → succeeded
                         ↓              ↓                ↓
                       failed         canceled          failed
                         ↓                                ↓
                      retrying                         retrying
                         ↓                                ↓
                      planning                         planning
```

## States

| State | Description | Transitions To |
|-------|-----------|---------------|
| `created` | Initialized, not yet triggered | scheduled, planning, canceled |
| `scheduled` | Queued for future execution (cron/delayed) | planning, canceled |
| `planning` | Agent reasoning about next action | awaiting_approval, executing, failed |
| `awaiting_approval` | Governance paused for human confirmation | executing, canceled, failed |
| `executing` | Running tool calls / generating output | planning, succeeded, failed |
| `succeeded` | Completed successfully | (terminal) |
| `failed` | Terminated — see failure taxonomy below | retrying or (terminal) |
| `retrying` | Policy allows retry | planning, failed |
| `canceled` | Operator/governance canceled | (terminal) |

## Invariants

1. **All runs pass through `planning`.** Even trivial one-shot tasks. Planning may be instantaneous but is never skipped. This ensures governance always has an interception point.
2. **Every state transition is traced.** Observability records: run_id, from_state, to_state, reason, timestamp.
3. **Governance intercepts at planning → executing.** Policy evaluation happens here.
4. **Approval timeout = canceled.** Default 15 min, configurable. Exceeding → `canceled` with reason `approval_timeout`.
5. **Canceled is always available** for any non-terminal run.

## Failure Taxonomy

| Reason | Description | Retry? | Alert |
|--------|-----------|--------|-------|
| `policy_denied` | Governance denied the action | No | Warning |
| `approval_timeout` | Human approval not received | No | Info |
| `budget_exceeded` | Hit spend limit | No (until reset) | Warning |
| `tool_failed` | Tool/skill returned error | If idempotent | Error |
| `backend_unavailable` | Memory/obs/runtime unreachable | Backoff | Critical |
| `model_failed` | LLM call failed | Backoff + fallback | Warning |
| `validation_failed` | Invalid output or constraint violation | No | Error |
| `operator_canceled` | Explicit cancellation | No | Info |

**Guarantee:** Every failed run MUST carry a specific failure reason. Adapters must not collapse distinct failures into generic errors.
