# Governance Adapter Contract

See `constitution/v0.4.0.md` §6.4 and §7 for full specification.

## Two-Tier Enforcement

| Mechanism | When | Latency | Blocking? |
|----------|------|---------|----------|
| Policy evaluation | Every side effect (except pure_read) | Milliseconds | No (for allow) |
| Human approval | Only for confirm capabilities | Minutes | Yes |

## Methods

- `evaluate(agent_id, action, context)` → allow / deny / require_approval
- `request_approval(agent_id, action, context)` → approved / denied / timeout
- `audit_log(agent_id, run_id, action, result, metadata)` → Append-only
- `get_policy(agent_id)` → Active policy
- `set_policy(agent_id, policy)` → Update policy
- `check_budget(agent_id)` → Remaining budget

## Audit Guarantees

Ordered, tamper-evident, exportable, independently verifiable.

## TODO

- Phase 1: Define mock implementation (always allow, log to stdout)
- Phase 2D: Build real thin governance layer
