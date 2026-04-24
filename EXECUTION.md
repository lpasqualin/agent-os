# Agent OS — Execution Checklist
_Roadmap v3.2 | April 2026 | Ax-reviewed_

Source of truth: Todoist → AI & Projects → Agent OS section.

---

## Ground Rules

- Sequence is fixed: **A0 → A1 → A2 (A2a, A2b) → A3 → B1 (B1a, B1b, B1c) → B2 → D1 → D2 (D2a, D2b, D2c) → ⬛ Gate → D3 → C → E → F → G → H**
- Do NOT start D3, C, E, F, G, or H until Core Loop Gate passes
- No phase sealed without tests
- Ax reviews before sealing any phase
- Runtime-native telemetry fields are adapter inputs, not Agent OS core fields unless they are semantically runtime-neutral
---

## Phase A — Journal & Audit

### A0: Refactor Legacy Model/Retry Spec Into Current Phases

- [ ] Audit existing model/retry spec artifacts against current phase structure
- [ ] Refactor or discard — nothing forward that doesn't fit Phase A–D contracts
- [ ] Confirm RunRecord field set against real OpenClaw cron JSONL: `job_id`, `run_id`, `attempt`, `model_requested`, `model_used`, `duration_ms`, `status`, `failure_class`
- [ ] No new code in A0 — analysis and reconciliation only
- [ ] A1 does not begin until RunRecord field set is confirmed

---

### A1: Journal Partitioning

**Files:** `src/agent_os/journal.py`, `src/agent_os/cli.py`, migration script, tests

- [ ] New journal writes go to `journal/YYYY/MM/{run_id}.json`
- [ ] `list_runs()` scans recursively across partitions, newest-first
- [ ] `agent-os journal stats`
- [ ] `agent-os journal export --format json|csv --since <date> --until <date>`
- [ ] One-time migration script using `requested_at` timestamp
- [ ] `runs`, `inspect`, `replay`, `journal latest` all unaffected
- [ ] ≥12 new tests

---

### A2: Tamper-Evident Audit Chain

**Files:** `src/agent_os/journal.py`, `src/agent_os/cli.py`, standalone verifier, tests

**A2a: Define RunRecord schema from real telemetry**
- [ ] Pull ≥10 real OpenClaw cron JSONL records
- [ ] Validate every RunRecord field maps to actual runtime output
- [ ] Lock schema before implementing hash chain

**A2b: Add failure taxonomy fields to journal model**
- [ ] Cross-reference 8-reason taxonomy against real OpenClaw failure modes
- [ ] Add or rename taxonomy entries where real data reveals gaps
- [ ] Failure taxonomy fields added to RunRecord and journal model

**Core:**
- [ ] `sequence_number` per agent (monotonically increasing)
- [ ] `prev_hash` per record (SHA-256 of previous record)
- [ ] `runtime_ref` included in hash input
- [ ] `agent-os journal verify` command
- [ ] Standalone verifier — no agent_os import required
- [ ] Modifying a prior record breaks verification
- [ ] Deleting a record breaks verification
- [ ] ≥8 new tests

---

### A3: Governance Decision Surfacing

**Files:** `src/agent_os/cli.py`, journal read/query helpers, registry + policy resolution helpers

- [ ] `agent-os governance summary`
- [ ] `agent-os governance audit <run_id>` — plain-English explanation of every decision
- [ ] `agent-os governance policy <agent_spec>`
- [ ] Each command explains: capability, action class, default behavior, override if any, effective decision
- [ ] Works over migrated journal data (post-A1)
- [ ] No new storage introduced
- [ ] ≥10 new tests

---

## Phase B — Policy Engine

### B1: Persistent Governance Adapter

**Files:** `src/agent_os/adapters/governance/persistent.py`, `contracts/retry_policy.md`, `contracts/model_policy.md`, tests

**B1a: Define RetryPolicy contract**
- [ ] Max 2 attempts
- [ ] Suppress on auth failure and usage limit
- [ ] Documented in `contracts/retry_policy.md`

**B1b: Define ModelPolicy contract**
- [ ] Derived from real ClawBot model usage and fallback behavior
- [ ] Documented in `contracts/model_policy.md`

**B1c: Wire failure taxonomy to policy decisions**
- [ ] Auth failure → no retry
- [ ] Usage limit → no retry
- [ ] Tool failure → retry if idempotent
- [ ] `evaluate()` uses taxonomy to determine retry eligibility

**Core:**
- [ ] `PersistentGovernance` under `~/.agent_os/governance/`
- [ ] `budget.json` — daily/monthly spend, resets midnight UTC
- [ ] Real-time `check_budget()` (disk, not cache)
- [ ] Rate limits per capability/agent (configurable)
- [ ] `get_policy()` and `set_policy()` implemented
- [ ] `evaluate()` <10ms benchmarked
- [ ] Budget survives process restart
- [ ] Deny after `daily_usd: 5.00` exceeded
- [ ] ≥15 new tests

---

### B2: Policy Override Enforcement

- [ ] Boot-time validation rejects permissive overrides (e.g., `email.send: allow` → boot fails)
- [ ] `evaluate()` rejects runtime circumvention
- [ ] Override direction auditable in every case
- [ ] Permissive override → clear boot failure
- [ ] Stricter override → succeeds and logged
- [ ] ≥6 new tests

---

## Phase D — Runtime & Portability

### D1: Runtime Compliance Tests

**Files:** `tests/compliance/test_runtime_contract.py`

- [ ] Validates: mapping, validation, failure typing, execution result shape
- [ ] Runtime adapters must ingest runtime-native telemetry
- [ ] Runtime adapters must normalize to RunRecord
- [ ] Runtime adapters must preserve `runtime_ref`
- [ ] Runtime adapters must map errors to failure taxonomy
- [ ] Runtime adapters must NOT require runtime schema changes
- [ ] Parameterized — any adapter passed as fixture
- [ ] `MockRuntime` passes
- [ ] `OpenClawRuntime` passes
- [ ] ≥15 contract tests

---

### D2: Real Runtime Adapter (OpenClaw)

**Files:** `src/agent_os/adapters/runtime/openclaw.py`, integration tests

**D2a: Validate RunRecord emission from live OpenClaw runs**
- [ ] Integration tests confirm RunRecord produced correctly from live execution
- [ ] Every field maps correctly from OpenClaw native output

**D2b: Validate retry behavior against real runtime failures**
- [ ] Live failure scenarios exercise RetryPolicy
- [ ] Auth failure suppression confirmed
- [ ] Usage limit suppression confirmed

**D2c: Validate model policy on cron/live execution paths**
- [ ] ModelPolicy exercised on cron-triggered path
- [ ] ModelPolicy exercised on live execution path
- [ ] Fallback chain behavior confirmed

**Core:**
- [ ] OpenClaw sandbox config (`~/openclaw-sandbox/config/openclaw.json`)
- [ ] `_CAPABILITY_MAP` expanded to all supported capabilities
- [ ] Prompt construction per capability
- [ ] Response normalization per skill
- [ ] Read OpenClaw native run/cron JSONL
- [ ] Extract: status, timestamps, model used, errors
- [ ] Map to RunRecord, store `runtime_ref`
- [ ] Do NOT duplicate full logs into journal
- [ ] Live tests pass for ≥4 capabilities
- [ ] Journal records: `runtime_target: "openclaw"`, real timestamps, actual output
- [ ] Failed runs use failure taxonomy (not generic errors)
- [ ] Passes D1 compliance suite
- [ ] All 428+ existing tests still pass
- [ ] Integration tests marked `@pytest.mark.integration`

---

## ⬛ Core Loop Proof Gate

**Nothing below starts until every box is checked.**

```
agent-os run clawbot tasks.create "Call dentist tomorrow 10am"
```

- [ ] Loads real agent spec (`specs/clawbot.agent.yaml`)
- [ ] Policy engine evaluates real capability with real budget tracking
- [ ] Runtime executes against real backend (OpenClaw)
- [ ] Runtime telemetry ingested by adapter
- [ ] RunRecord produced (normalized)
- [ ] Journal entry written with tamper-evident hash chain
- [ ] `agent-os inspect --latest` works
- [ ] `agent-os replay <run_id>` works
- [ ] `agent-os governance audit <run_id>` explains why it was allowed

---

## Phase D — Portability Proof *(post-gate)*

### D3: LocalFunction Runtime Adapter

- [ ] `LocalFunctionRuntime` — capabilities mapped to local Python functions
- [ ] No subprocess, no external service
- [ ] Passes D1 compliance suite
- [ ] Same agent spec runs on both `OpenClawRuntime` and `LocalFunctionRuntime`
- [ ] Journal structure identical across both runtimes
- [ ] Policy/governance shown to be runtime-independent

---

## Expansion Phases *(all blocked until Gate passes)*

| Phase | Name |
|-------|------|
| C1/C2 | Approval Adapter |
| E1/E2 | Observability Engine |
| F1/F2 | Memory Adapter |
| G1/G2 | Fleet Manager |
| H1/H2 | Compliance & Export |

---

## What You Are NOT Building Yet

- Fleet features, approval UX, memory sophistication, observability polish, compliance exports, dashboard

**You are building:**
```
A0 reconciliation → journal structure → tamper evidence →
governance visibility → persistent policy → runtime compliance →
real execution (D2a/b/c) → core loop proof → portability
```
