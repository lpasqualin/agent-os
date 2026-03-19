# Governance Adapter Contract

See `constitution/v0.4.0.md` §6.4 and §7.

Two-tier enforcement: automatic policy evaluation on all side effects, human approval only for gated capabilities.

## Two Tiers

| Tier | Mechanism | When | Latency | Blocks? |
|------|----------|------|---------|---------|
| 1 | Policy evaluation | Every side effect (except pure_read) | Milliseconds | No (for allow) |
| 2 | Human approval | Only for policy = confirm | Minutes | Yes (awaiting_approval) |

**Do not confuse these.** Tier 1 is always-on and cheap. Tier 2 is rare and expensive.

## Methods

| Method | Signature | Description |
|--------|----------|-------------|
| evaluate | `(agent_id, action, context)` | Returns allow / deny / require_approval. Must be fast. |
| request_approval | `(agent_id, action, context)` | Send to operator channel. Returns approved / denied / timeout. |
| audit_log | `(agent_id, run_id, action, result, metadata)` | Append-only record. Input/output hashed by default. |
| get_policy | `(agent_id)` | Return active governance policy |
| set_policy | `(agent_id, policy)` | Update governance policy |
| check_budget | `(agent_id)` | Return remaining budget for current period |

## Policy Override Rules

1. Agent specs declare per-capability policy: `allow`, `confirm`, or `deny`.
2. Overrides may only be **stricter** than the action class default, never more permissive.
3. Example: `tasks.delete` has action_class `irreversible_mutation` which defaults to `confirm`. An agent spec can set `deny` but cannot set `allow`.

## Approval Gates

- All `irreversible_mutation` defaults to `confirm`
- All `privileged_control` defaults to `confirm`
- `external_mutation` to unvetted targets defaults to `confirm` on first use
- Timeout: 15 min default, configurable. Exceeded → run canceled.

## Audit Trail Guarantees

Audit records MUST be:

1. **Ordered** — monotonically increasing sequence per agent
2. **Tamper-evident** — post-creation modification must be detectable
3. **Exportable** — complete trail exportable as structured data
4. **Independently verifiable** — integrity verifiable without trusting runtime or adapter

Implementation chooses the mechanism. The guarantees are non-negotiable.

## Invariants

1. evaluate() MUST complete in < 10ms for allow/deny decisions.
2. evaluate() MUST check: capability allowed? Budget remaining? Rate limit? Action class default?
3. evaluate() MUST reject policy overrides more permissive than action class defaults.
4. audit_log() MUST hash inputs/outputs by default (privacy-first). Full content only when policy requires.
5. check_budget() MUST reflect real-time spend, not cached values.
