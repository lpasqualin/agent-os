# Action Taxonomy Contract

See `constitution/v0.4.0.md` §3.

Defines what "side effect" means. Every capability declares exactly one action class.

## Action Classes

| Class | Governance Default | Audit Default | Description |
|-------|-------------------|--------------|-------------|
| `pure_read` | Exempt from eval | Minimal | No mutation, no cost, no privacy concern |
| `sensitive_read` | Allow + audit | Full | Privacy-sensitive or crosses trust boundary |
| `billable_read` | Allow + budget check | Standard | Incurs cost per call |
| `internal_mutation` | Allow | Standard | Changes state within agent's own scope |
| `external_mutation` | Confirm for unvetted; allow for established | Full | Changes state in external system |
| `irreversible_mutation` | Confirm | Full + justification | Cannot be undone |
| `privileged_control` | Confirm | Full + justification | Changes to agent system itself |

## Invariants

1. Every capability in `capabilities/registry.yaml` MUST declare an `action_class`.
2. `pure_read` is the ONLY class exempt from governance evaluation.
3. Governance defaults derive from action class. Agent specs override stricter only, never more permissive.
4. When a capability straddles two classes, it takes the more restrictive one.
5. Action class is stable across runtimes — `tasks.write` is `external_mutation` whether the runtime uses Todoist, Asana, or anything else.

## Governance Linkage

| action_class | Tier 1 (auto) | Tier 2 (human) | Budget check | Justification |
|-------------|--------------|----------------|-------------|---------------|
| `pure_read` | No | No | No | No |
| `sensitive_read` | Yes | No | No | No |
| `billable_read` | Yes | No | Yes | No |
| `internal_mutation` | Yes | No | No | No |
| `external_mutation` | Yes | First-use for unvetted | No | No |
| `irreversible_mutation` | Yes | Yes (default) | Yes | Yes |
| `privileged_control` | Yes | Yes (always) | Yes | Yes |
