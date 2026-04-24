# Agent OS — Build Roadmap v3.2

**April 2026**
**Author:** Leo Pasqua
**Architectural review:** Ax
**Delta from v3.1:** Runtime telemetry ingestion + journal scope correction (execution truth vs. audit truth split). A0 added. Phase 1 (Model & Retry Contracts) absorbed into A0. D3 moved post-gate.

> Agent OS is a control plane for agents — not an agent itself.
> The product is the loop: Agent Spec → Chassis → Policy → Runtime → Result → Journal.
> Everything else is expansion. Nothing ships until the loop is real.

---

## Core Principle (v3.2)

**Agent OS does not own execution truth. It owns audit truth.**

```
Agent Spec → Chassis → Policy → Runtime → Result → Journal

Runtime = execution truth   (OpenClaw — not controlled by Agent OS)
Journal  = audit truth      (normalized, tamper-evident, independently verifiable)
```

Adapters bridge the two. The journal stores only normalized RunRecords — not raw logs, not token streams, not model traces.

---

## RunRecord Schema (required — every run normalizes into this)

```json
{
  "run_id": "...",
  "agent_id": "...",
  "capability": "tasks.create",
  "action_class": "external_mutation",
  "policy_decision": "allow",
  "runtime_target": "openclaw",
  "runtime_ref": "native_run_id",
  "status": "succeeded",
  "failure_reason": null,
  "started_at": "...",
  "ended_at": "...",
  "result_summary": "...",
  "sequence_number": 42,
  "prev_hash": "..."
}
```

Adapter-observed telemetry fields used to validate RunRecord normalization:
job_id, runtime_run_id, attempt, model_requested, model_used, duration_ms, status, failure_class

---

## Journal (redefined)

**Stores ONLY:** `run_id` / `agent_id`, `capability` + `action_class`, `policy_decision`, `runtime_target` + `runtime_ref`, `status` + `failure_reason`, timestamps, `result_summary`, `sequence_number` + `prev_hash`.

**Does NOT store:** token streams, step-by-step tool calls, raw logs, model reasoning traces.

---

## Core Loop Proof Gate

**Agent OS is not real until this demo passes end-to-end with zero mock adapters:**

```
agent-os run clawbot tasks.create "Call dentist tomorrow 10am"
```

1. Loads real agent spec
2. Policy engine evaluates real capability with persistent budget tracking
3. Runtime executes against real backend (OpenClaw)
4. Runtime telemetry ingested by adapter
5. RunRecord produced (normalized)
6. Journal entry written with tamper-evident hash chain
7. `agent-os inspect --latest` works
8. `agent-os replay <run_id>` works
9. `agent-os governance audit <run_id>` explains the decision

**Nothing after D2 starts until this passes.**

---

## Current State (April 2026)

| Metric | Value |
|--------|-------|
| Constitution | v0.4.0 — FROZEN |
| Roadmap | v3.2 — LOCKED |
| Tests | 428 passing |
| Foundation | Schema, registry, agent spec, contracts, mock adapters — complete |
| OpenClawRuntime | Partial — 3 capabilities, sandbox not configured |
| Journal | Flat directory, no partitioning, no hash chain |
| Core loop | **ALL MOCK** — no real policy, no real runtime, no tamper-evident journal |

---

## Phase A — Journal & Audit

### A0: Refactor Legacy Model/Retry Spec Into Current Phases

The prior Phase 1 (Model & Retry Contracts) work is absorbed here. Before partitioning begins, any existing model/retry spec artifacts must be reconciled with the current phase structure, and the RunRecord field set must be confirmed against real OpenClaw telemetry.

**Deliverables:**
1. Audit any existing model/retry spec artifacts against the current phase structure
2. Refactor or discard — nothing carries forward that doesn't fit Phase A–D contracts
3. Confirm RunRecord field set against real OpenClaw cron JSONL: `job_id`, `run_id`, `attempt`, `model_requested`, `model_used`, `duration_ms`, `status`, `failure_class`

**Acceptance criteria:**
- No orphaned spec artifacts from prior work
- RunRecord field set confirmed against real telemetry before A1 begins
- No new code written in A0 — analysis and reconciliation only

### A1: Journal Partitioning

**Goal:** Move journal from flat files to partitioned storage.

**Deliverables:**
1. Journal writes to `journal/YYYY/MM/{run_id}.json` instead of flat `journal/{run_id}.json`
2. `list_runs()` scans recursively, newest-first ordering preserved
3. `agent-os journal stats` — total runs, date range, disk usage, runs by status, runs per day
4. `agent-os journal export --format json|csv --since <date> --until <date>`
5. Migration script: moves existing flat files using `requested_at` timestamp
6. Optional: `agent-os journal archive --older-than N` compresses month partitions to tar.gz

**Acceptance criteria:**
- New runs write to `journal/YYYY/MM/run_xxx.json` automatically
- `list_runs()` correct across multiple partition directories
- Migration moves all existing files without data loss
- `runs`, `inspect`, `replay`, `journal latest` all unaffected
- Tests: ≥12 new tests

### A2: Tamper-Evident Audit Chain

**Goal:** Journal records satisfy constitution §6.4.1 audit guarantees.

**A2a: Define RunRecord schema from real telemetry**
- Pull real OpenClaw cron JSONL records
- Validate RunRecord field set maps correctly to actual runtime output
- Lock the schema before implementing the hash chain

**A2b: Add failure taxonomy fields to journal model**
- Cross-reference the 8-reason failure taxonomy against real failure modes from OpenClaw runs
- Add or rename taxonomy entries where real data reveals gaps
- Failure taxonomy fields added to RunRecord and journal model

**Core deliverables:**
1. Each RunRecord includes `sequence_number` (monotonically increasing per agent) and `prev_hash` (SHA-256 of previous record)
2. `runtime_ref` included in hash input
3. `agent-os journal verify` — walks chain, detects modified/deleted/reordered records
4. Standalone verifier — no agent_os import required

**Acceptance criteria:**
- Modifying any prior record breaks verification
- Deleting a record breaks verification
- New records include sequence + hash automatically
- RunRecord schema validated against ≥10 real OpenClaw runs (A2a)
- Zero unclassifiable failures in real run sample (A2b)
- Tests: ≥8 new tests

### A3: Governance Decision Surfacing

**Goal:** Read-only queries over existing journal data. No new storage.

**Deliverables:**
1. `agent-os governance summary` — allow/deny/require_approval counts by capability and action class
2. `agent-os governance audit <run_id>` — capability, action class, policy evaluated, decision, override direction, plain-English explanation
3. `agent-os governance policy <agent_spec>` — resolved policy map for an agent

**Acceptance criteria:**
- All commands work against migrated journal data (post-A1)
- Plain-English explanations are correct
- No new storage introduced
- Tests: ≥10 new tests

---

## Phase B — Policy Engine

### B1: Persistent Governance Adapter

**Goal:** Replace `MockGovernance` with a real disk-backed adapter.

**B1a: Define RetryPolicy contract**
- Derived from real ClawBot retry patterns: max 2 attempts, suppress on auth failure and usage limit
- Contract documented in `contracts/retry_policy.md`

**B1b: Define ModelPolicy contract**
- Derived from real ClawBot model usage and fallback behavior
- Contract documented in `contracts/model_policy.md`

**B1c: Wire failure taxonomy to policy decisions**
- `evaluate()` uses failure taxonomy to determine retry eligibility
- Auth failure → no retry. Usage limit → no retry. Tool failure → retry if idempotent.

**Core deliverables:**
1. `PersistentGovernance` adapter backed by `~/.agent_os/governance/`
2. Budget tracking: spend per agent per day/month in `budget.json`, resets daily midnight UTC
3. `evaluate()` checks: capability allowed? Budget? Rate limit? Action class default? — <10ms
4. `check_budget()` reads disk, not cache
5. Rate limiting: configurable calls-per-minute per capability per agent
6. `get_policy()` and `set_policy()` implemented
7. RetryPolicy and ModelPolicy contracts wired to evaluation logic

**Acceptance criteria:**
- After exceeding `daily_usd: 5.00`, `evaluate()` returns `"deny"`
- Budget survives process restart
- Rate limit enforcement works
- `evaluate()` <10ms benchmarked
- RetryPolicy contract documented and implemented (B1a)
- ModelPolicy contract documented and implemented (B1b)
- Failure taxonomy drives retry decisions (B1c)
- Tests: ≥15 new tests

### B2: Policy Override Enforcement

**Goal:** Make permissive override violations impossible.

**Deliverables:**
1. Boot-time validation rejects permissive overrides (`email.send: allow` fails — `irreversible_mutation` defaults to `confirm`)
2. `evaluate()` rejects runtime circumvention
3. Every override audited with direction noted

**Acceptance criteria:**
- Permissive override → boot failure with clear error
- Stricter override → boot succeeds, logged
- Tests: ≥6 new tests

---

## Phase D — Runtime & Portability

### D1: Runtime Compliance Tests

**Goal:** Formalize what a compliant runtime adapter must prove.

**Deliverables:**
1. Compliance suite at `tests/compliance/test_runtime_contract.py`
2. Validates every invariant from `contracts/runtime.md`
3. Runtime adapters must: ingest runtime-native telemetry, normalize to RunRecord, preserve `runtime_ref`, map errors to failure taxonomy, NOT require runtime schema changes
4. Parameterized — any adapter passed as fixture

**Acceptance criteria:**
- `MockRuntime` and `OpenClawRuntime` both pass
- Tests: ≥15 contract tests

### D2: Real Runtime Adapter (OpenClaw)

**Goal:** One real runtime adapter live behind the adapter boundary.

**D2a: Validate RunRecord emission from live OpenClaw runs**
- Integration tests confirm RunRecord is produced correctly from live execution
- Every field maps correctly from OpenClaw native output

**D2b: Validate retry behavior against real runtime failures**
- Live failure scenarios exercise RetryPolicy
- Auth failure and usage limit suppression confirmed in integration tests

**D2c: Validate model policy on cron/live execution paths**
- ModelPolicy exercised on both cron-triggered and live execution paths
- Fallback chain behavior confirmed

**Core deliverables:**
1. Sandbox config: `~/openclaw-sandbox/config/openclaw.json`
2. `_CAPABILITY_MAP` expanded to all capabilities ClawBot has skills for
3. Prompt construction per capability
4. Response normalization per skill
5. Telemetry ingestion: reads OpenClaw native run/cron JSONL, extracts status/timestamps/model/errors, maps to RunRecord, stores `runtime_ref` — does NOT duplicate full logs into journal

**Acceptance criteria:**
- Live tests pass for ≥4 capabilities
- RunRecord emission validated from live runs (D2a)
- Retry behavior validated against real failures (D2b)
- Model policy validated on cron and live paths (D2c)
- Journal records include `runtime_target: "openclaw"`, real timestamps, actual output
- Failed runs use failure taxonomy, not generic errors
- Passes D1 compliance suite
- All 428+ existing tests still pass
- Integration tests marked `@pytest.mark.integration`

---

## ⬛ CORE LOOP PROOF GATE

**Nothing below starts until this passes.**

- [ ] Loads real agent spec
- [ ] Policy engine evaluates real capability with real budget tracking
- [ ] Runtime executes against real backend
- [ ] Runtime telemetry ingested, RunRecord produced
- [ ] Journal entry written with tamper-evident hash chain
- [ ] `agent-os inspect --latest` works
- [ ] `agent-os replay <run_id>` works
- [ ] `agent-os governance audit <run_id>` explains the decision

---

## Phase D — Portability Proof *(post-gate)*

### D3: LocalFunction Runtime Adapter

**Goal:** Prove portability is real, not claimed.

**Deliverables:**
1. `LocalFunctionRuntime` — capabilities mapped to local Python functions, no subprocess, no external service
2. Passes D1 compliance suite
3. Same agent spec boots and runs on both runtimes
4. Same journal structure from both runtimes
5. Policy/governance shown to be runtime-independent

---

## ── EXPANSION PHASES ── *(all blocked until Core Loop Gate passes)*

---

## Phase C — Approval Adapter

**Depends on: B1 + D2**

### C1: Approval Adapter Interface
1. `ApprovalAdapter` ABC: `request_approval()`, `check_status()`, `health()`
2. `MockApproval` — auto-approves
3. `ConsoleApproval` — stdin prompt for local/dev use
4. Timeout: 15 min default, configurable
5. Governance delegates to `ApprovalAdapter` — does not own the mechanism

### C2: First Real Approval Adapter
1. Real adapter (e.g., `TelegramApproval`) via Bot API
2. Message: capability, action class, risk level, task summary, approve/deny instructions
3. Reply handling: approve/deny/timeout
4. Graceful degradation: channel unreachable → warning + fallback, never crashes

---

## Phase E — Observability

**Note (v3.2):** Observability is NOT sourced only from journal. May query runtime telemetry directly, use normalized RunRecords, or combine both.

### E1: Observability Adapter (File-Based Reference)
1. `FileObservability` — structured trace files at `~/.agent_os/traces/`
2. One trace per run: `state_transition`, `tool_call`, `governance_decision`, `error`
3. `query()` with filters: `agent_id`, `run_id`, `time_range`, `event_type`, `failure_reason`
4. Replace `MockObservability` in chassis boot

### E2: Metrics Engine
1. `agent-os metrics` — success rate, mean/p95 duration, capability usage, failure breakdown
2. `--agent`, `--since` scoping. `--format json` for export
3. `--model-drift` — flags behavior changes correlated with model version changes

---

## Phase F — Memory

### F1: Memory Adapter (Reference Implementation)
Full `MemoryAdapter` per §6.2.1 entry schema and §6.2.2 category laws.

### F2: Memory + Chassis Integration
Replace `MockMemory()` in boot. Memory ops in traces. Scope isolation enforced.

---

## Phase G — Fleet

### G1: Agent Registry
`agent-os agents list/boot/status`. Multi-agent with isolated state.

### G2: Fleet Specs
Specs for planned fleet. All validate and boot.

---

## Phase H — Compliance

### H1: Regulatory Mapping
Static mapping files: `compliance/nist-ai-rmf.yaml`, `compliance/soc2.yaml`, `compliance/iso42001.yaml`

### H2: Compliance Report Generator
`agent-os compliance report` — markdown with dynamic evidence from journal + traces.

---

## Build Sequence

| Order | Phase | Name | Depends On | Status |
|-------|-------|------|------------|--------|
| 1 | A0 | Refactor legacy model/retry spec | — | **Next** |
| 2 | A1 | Journal Partitioning | A0 | Not started |
| 3 | A2 | Tamper-Evident Audit Chain | A1 | Not started |
| 3a | A2a | RunRecord schema from real telemetry | A1 | Not started |
| 3b | A2b | Failure taxonomy fields to journal model | A1 | Not started |
| 4 | A3 | Governance Decision Surfacing | A1 | Not started |
| 5 | B1 | Persistent Governance Adapter | A2 | Not started |
| 5a | B1a | RetryPolicy contract | — | Not started |
| 5b | B1b | ModelPolicy contract | — | Not started |
| 5c | B1c | Wire failure taxonomy to policy | B1a/b | Not started |
| 6 | B2 | Policy Override Enforcement | B1 | Not started |
| 7 | D1 | Runtime Compliance Tests | — | Not started |
| 8 | D2 | Real Runtime Adapter (OpenClaw) | D1 | Partial |
| 8a | D2a | Validate RunRecord from live runs | D2 | Not started |
| 8b | D2b | Validate retry on real failures | D2 | Not started |
| 8c | D2c | Validate model policy on cron/live | D2 | Not started |
| | | **⬛ CORE LOOP PROOF GATE** | A2+B1+D2 | |
| 9 | D3 | LocalFunction Runtime (Portability Proof) | D1+Gate | Blocked |
| 10 | C1 | Approval Adapter Interface | B1+D2+Gate | Blocked |
| 11 | C2 | First Real Approval Adapter | C1+Gate | Blocked |
| 12 | E1 | Observability Adapter | Gate | Blocked |
| 13 | E2 | Metrics Engine | E1 | Blocked |
| 14 | F1 | Memory Adapter | Gate | Blocked |
| 15 | F2 | Memory + Chassis Integration | F1 | Blocked |
| 16 | G1 | Agent Registry | Gate | Blocked |
| 17 | G2 | Fleet Specs | G1 | Blocked |
| 18 | H1 | Regulatory Mapping | E2+B2 | Blocked |
| 19 | H2 | Compliance Report Generator | H1 | Blocked |

---

## Architecture Invariants (v3.2)

1. No runtime name appears as a phase title — runtimes are adapter implementations
2. No channel name appears as a phase title — channels are adapter implementations
3. Every side-effecting action passes through governance — no exceptions
4. LLMs propose, the runtime decides — agents never directly mutate real systems
5. Own the contracts, not the engines — we build adapters, not backends
6. Journal is append-only and tamper-evident — no record modified after creation
7. Secrets never appear in portable specs — resolved at deploy time only
8. `pure_read` is the only governance exemption — everything else gets evaluated
9. Test everything — no phase sealed without tests, Ax reviews before sealing
10. No expansion layer may outrun the core loop
11. The journal is the authoritative audit record, not the raw execution source — runtime telemetry = execution truth, journal = audit truth, adapters bridge the two, discrepancies must be explainable not overridden

---

> *You are not building a better agent.*
> *You are building the system companies will need when they have 100 agents and are scared of them.*
> *Prove the loop first. Expand after.*

*Leo Pasqua — April 2026*
*With architectural review by Ax*
