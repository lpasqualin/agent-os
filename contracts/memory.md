# Memory Adapter Contract

See `constitution/v0.4.0.md` §6.2.

Agent memory semantics. Methods reflect how agents interact with memory: remembering, recalling, forgetting.

## Methods

| Method | Signature | Description |
|--------|----------|-------------|
| remember | `(agent_id, entry)` | Store a memory entry per entry schema |
| recall | `(agent_id, query, filters)` | Semantic search. Filters: category, scope, confidence_min, time_range, source |
| forget | `(agent_id, selector)` | Remove entries by ID, category, or filter |
| list | `(agent_id, filters)` | Structured query only (no semantic matching) |
| compact | `(agent_id)` | Summarize old entries, merge duplicates, prune expired/low-confidence |
| export | `(agent_id, format)` | Export as JSON/YAML. Required for portability. |

## Entry Schema

| Field | Type | Required | Description |
|-------|------|---------|-------------|
| id | string | auto | Generated on remember() |
| category | enum | yes | fact, preference, event, decision, learning, context |
| content | string | yes | The memory content |
| scope | enum | yes | agent, shared, global |
| confidence | float | no | 0.0–1.0, default 1.0 |
| source | enum | no | user_stated, inferred, tool_output, system |
| supersedes | string | no | ID of entry this replaces |
| created_at | timestamp | auto | Creation time |
| expires_at | timestamp | no | TTL. Auto-set for some categories. |

## Category Laws

| Category | Durability | Rules |
|---------|-----------|-------|
| `fact` | Durable | Must have source. Supersedes conflicting facts. |
| `preference` | Durable | Only from user_stated or repeated pattern. Never single observation. |
| `event` | 30-day TTL | Must include timestamp. Promote only if explicitly significant. |
| `decision` | Durable | Must include reasoning. Never deleted, only superseded. |
| `learning` | 30-day TTL | Created after runs. Reference source run_id. |
| `context` | 24-hour TTL | Strict. Never promoted. Compaction prunes aggressively. |

**HARD LAW:** tool_output must never become memory without summarization. Raw output is traced via observability. Memory entries must be extracted facts, decisions, or learnings.

## Scope Authority

| Scope | Write | Read | Conflicts | Governance |
|-------|-------|------|-----------|-----------|
| `agent` | Owning agent only | Owning agent only | N/A | internal_mutation |
| `shared` | Agents with shared_write | Agents with shared_read | Last-write-wins + supersedes chain | external_mutation; first write to new namespace = confirm |
| `global` | Agents with global_write (highest trust) | All agents | Operator arbitrates | privileged_control — always confirm |

**Guarantee:** No silent scope promotion. Promoting agent → shared/global requires a new remember() at target scope.

## Invariants

1. remember() MUST reject entries with invalid categories.
2. remember() MUST enforce category durability defaults (TTL).
3. remember() MUST reject raw tool_output as content without summarization flag.
4. forget() on `decision` category MUST be rejected (decisions are only superseded).
5. export() MUST produce valid structured data with no proprietary formats.
6. compact() MUST NOT delete `decision` or `learning` entries.
