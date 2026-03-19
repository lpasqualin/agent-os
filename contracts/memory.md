# Memory Adapter Contract

See `constitution/v0.4.0.md` §6.2 for full specification.

## Methods

- `remember(agent_id, entry)` → Store per entry schema
- `recall(agent_id, query, filters)` → Semantic search
- `forget(agent_id, selector)` → Remove by ID/category/filter
- `list(agent_id, filters)` → Structured query
- `compact(agent_id)` → Summarize, merge, prune
- `export(agent_id, format)` → JSON/YAML (required for portability)

## Entry Schema

See §6.2.1: id, category, content, scope, confidence, source, supersedes, created_at, expires_at

## Category Laws

See §6.2.2: fact, preference, event, decision, learning, context — each with durability rules.

## Scope Authority

See §6.2.3: agent (private), shared (privileged), global (highest trust).

## TODO

- Phase 1: Define mock implementation
- Phase 2C: Evaluate Mem0 vs Zep
