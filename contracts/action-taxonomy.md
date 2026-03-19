# Action Taxonomy Contract

See `constitution/v0.4.0.md` §3 for full specification.

## Action Classes

| Class | Governance Default | Audit Default |
|-------|-------------------|--------------|
| pure_read | Exempt from eval | Minimal |
| sensitive_read | Allow with audit | Full |
| billable_read | Allow with budget check | Standard |
| internal_mutation | Allow | Standard |
| external_mutation | Confirm for unvetted | Full |
| irreversible_mutation | Confirm | Full + justification |
| privileged_control | Confirm | Full + justification |

## Rules

- Every capability declares its action class
- Governance defaults from class; spec overrides stricter only
- When in doubt, classify up
- Class is stable across runtimes

## TODO

- Phase 1: Encode in capability registry validation
