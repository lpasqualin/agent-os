# Run Lifecycle Contract

See `constitution/v0.4.0.md` §5 for full specification.

## States

created → scheduled → planning → awaiting_approval → executing → succeeded / failed / canceled

## Key Invariants

- All runs pass through `planning` (never skipped)
- Every state transition is traced
- Governance intercepts at planning → executing boundary
- Approval timeout: 15 min default
- Canceled always available for non-terminal runs

## Failure Taxonomy (§5.1)

policy_denied, approval_timeout, budget_exceeded, tool_failed, backend_unavailable, model_failed, validation_failed, operator_canceled

## TODO

- Phase 1: Implement in mock runtime adapter
