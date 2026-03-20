"""Agent OS CLI — the interface to the chassis.

Usage:
    agent-os boot <spec_path> [--registry <registry_path>]
    agent-os journal latest
    agent-os runs [--limit N]
    python -m agent_os.cli boot specs/clawbot.agent.yaml
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent_os.chassis import Chassis
from agent_os.adapters.runtime.mock_runtime import MockRuntime
from agent_os.adapters.runtime.openclaw_runtime import OpenClawRuntime
from agent_os.journal import ExecutionJournal


def _default_adapter_factory(target: str):
    """Select a runtime adapter by target name for CLI invocations."""
    if target == "openclaw":
        return OpenClawRuntime()
    return MockRuntime()


def find_project_root() -> Path:
    """Walk up from CWD to find the agent-os project root (has capabilities/)."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "capabilities" / "registry.yaml").exists():
            return parent
    return current


def cmd_boot(args: argparse.Namespace) -> int:
    """Boot an agent through the chassis."""
    project_root = find_project_root()

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = project_root / spec_path

    registry_path = Path(args.registry) if args.registry else project_root / "capabilities" / "registry.yaml"
    if not registry_path.is_absolute():
        registry_path = project_root / registry_path

    print(f"Agent OS v0.1.0")
    print(f"Booting: {spec_path.name}")
    print(f"Registry: {registry_path.name}")
    print()

    chassis = Chassis(registry_path=registry_path, adapter_factory=_default_adapter_factory)
    report = chassis.boot(spec_path)
    print(report.print_report())

    if not report.success:
        return 1

    # Run a mock task to prove the full pipeline
    print("Executing mock task through chassis...")
    print()
    result = chassis.execute_task("mock_morning_briefing")

    print(f"  Run ID:      {result.get('run_id', 'N/A')}")
    print(f"  Status:      {result.get('status', 'N/A')}")
    print(f"  Capability:  {result.get('capability_used', 'N/A')}")
    if result.get("failure_reason"):
        print(f"  Failure:     {result['failure_reason']}")
    print()

    # Print lifecycle
    lifecycle = result.get("lifecycle", [])
    if lifecycle:
        print("  Run Lifecycle:")
        for step in lifecycle:
            reason = f" ({step['reason']})" if step.get("reason") else ""
            print(f"    {step['from']} -> {step['to']}{reason}")
    print()

    # Verify planning was hit (acceptance criteria)
    states_visited = set()
    for step in lifecycle:
        states_visited.add(step["from"])
        states_visited.add(step["to"])

    if "planning" in states_visited:
        print("  [PASS] Lifecycle passed through 'planning' state")
    else:
        print("  [FAIL] Lifecycle did NOT pass through 'planning' state")
        return 1

    print()
    print("Boot and execution complete.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run a capability through the sandbox chassis and print a structured result."""
    project_root = find_project_root()

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = project_root / spec_path

    registry_path = (
        Path(args.registry) if getattr(args, "registry", None)
        else project_root / "capabilities" / "registry.yaml"
    )
    if not registry_path.is_absolute():
        registry_path = project_root / registry_path

    capability = args.capability
    journal_dir = project_root / ".agent_os" / "journal"

    print(f"Agent OS — run")
    print(f"Spec:       {spec_path.name}")
    print(f"Capability: {capability}")
    print()

    chassis = Chassis(
        registry_path=registry_path,
        adapter_factory=_default_adapter_factory,
        journal_dir=journal_dir,
    )
    report = chassis.boot(spec_path)

    if not report.success:
        print("BOOT FAILED:")
        for err in report.errors:
            print(f"  {err}")
        return 1

    result = chassis.execute_task(capability)

    run_id = result.get("run_id", "N/A")
    status = result.get("status", "N/A")
    cap_used = result.get("capability_used", capability)
    output = result.get("output") or ""
    error = result.get("error") or ""
    lifecycle = result.get("lifecycle", [])

    print(f"Run ID:     {run_id}")
    print(f"Status:     {status}")
    print(f"Capability: {cap_used}")

    if output:
        summary = (output[:120] + "...") if len(output) > 120 else output
        print(f"Result:     {summary}")
    if error:
        print(f"Error:      {error[:120]}")

    if lifecycle:
        print()
        print("Lifecycle:")
        for step in lifecycle:
            reason = f" ({step['reason']})" if step.get("reason") else ""
            print(f"  {step['from']} -> {step['to']}{reason}")

    journal = ExecutionJournal(journal_dir)
    latest = journal.read_latest()
    if latest and latest.run_id == run_id:
        print()
        print(f"Journal:    {run_id}.json written")

    return 0


def cmd_journal_latest(args: argparse.Namespace) -> int:
    """Print the most recent journal entry as pretty-printed JSON."""
    project_root = find_project_root()
    journal = ExecutionJournal(project_root / ".agent_os" / "journal")
    record = journal.read_latest()

    if record is None:
        print("Journal is empty.")
        return 0

    print(json.dumps(json.loads(record.model_dump_json()), indent=2))
    return 0


# ── Status normalization ──────────────────────────────────────
#
# Audit of journal status values found at Phase 4A (2026-03-20):
#   'succeeded' → SUCCESS         (84 records)
#   'failed'    → FAILED          (63 records)
#   'rejected'  → CAPABILITY_ERROR (30 records — capability rejected by adapter or policy)
#   'timed_out' → TIMEOUT         (19 records)
#   'canceled'  → FAILED          (0 observed; possible from chassis approval-gate path)
#
# Normalization is applied at read time only — journal files are never mutated.
# Canonical display values: SUCCESS | FAILED | CAPABILITY_ERROR | TIMEOUT

_FAILURE_STATUSES: frozenset[str] = frozenset({"FAILED", "CAPABILITY_ERROR", "TIMEOUT"})

_STATUS_MAP: dict[str, str] = {
    "succeeded":       "SUCCESS",
    "success":         "SUCCESS",
    "failed":          "FAILED",
    "failure":         "FAILED",
    "canceled":        "FAILED",
    "cancelled":       "FAILED",
    "rejected":        "CAPABILITY_ERROR",
    "capability_error":"CAPABILITY_ERROR",
    "timed_out":       "TIMEOUT",
    "timeout":         "TIMEOUT",
    "timed-out":       "TIMEOUT",
}


def _normalize_status(raw: str) -> str:
    """Map a raw journal status string to a canonical display value.

    Canonical values: SUCCESS, FAILED, CAPABILITY_ERROR, TIMEOUT.
    Unrecognized values default to FAILED (safe fallback).
    Input is matched case-insensitively.
    """
    return _STATUS_MAP.get(str(raw).lower(), "FAILED")


def _filter_rows(
    rows: list[dict],
    status_filter: str | None,
    capability_filter: str | None,
) -> list[dict]:
    """Apply additive (AND) filters to a list of run rows.

    status_filter and capability_filter are both case-insensitive.
    status_filter is compared against the normalized canonical value.
    """
    result = rows
    if status_filter:
        target = _normalize_status(status_filter)
        result = [r for r in result if _normalize_status(r.get("status", "")) == target]
    if capability_filter:
        cap_lower = capability_filter.lower()
        result = [r for r in result if (r.get("capability") or "").lower() == cap_lower]
    return result


def _print_runs_table(rows: list[dict]) -> None:
    """Print a formatted runs table.

    Status values are shown as-stored in the journal (raw).
    Normalization is applied only for filter comparisons and --summary counts.
    """
    header = f"{'RUN_ID':<20}  {'CAPABILITY':<16}  {'STATUS':<14}  STARTED_AT"
    print()
    print(header)
    print("-" * len(header))
    for r in rows:
        started = str(r.get("requested_at", ""))[:19].replace("T", " ")
        print(
            f"{str(r['run_id']):<20}  "
            f"{str(r.get('capability') or ''):<16}  "
            f"{str(r.get('status', '')):<14}  "
            f"{started}"
        )
    print()


def _cmd_runs_summary(journal: ExecutionJournal) -> int:
    """Print aggregate counts and bookmarks across all runs."""
    all_rows = journal.list_runs(limit=10000)

    if not all_rows:
        print("No runs found.")
        return 0

    counts: dict[str, int] = {
        "SUCCESS": 0,
        "FAILED": 0,
        "CAPABILITY_ERROR": 0,
        "TIMEOUT": 0,
    }
    for r in all_rows:
        key = _normalize_status(r.get("status", ""))
        counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values())

    print(f"Total runs:        {total}")
    print(f"SUCCESS:           {counts['SUCCESS']}")
    print(f"FAILED:            {counts['FAILED']}")
    print(f"CAPABILITY_ERROR:  {counts['CAPABILITY_ERROR']}")
    print(f"TIMEOUT:           {counts['TIMEOUT']}")
    print()

    # Most recent run (all_rows already newest-first)
    latest = all_rows[0]
    latest_started = str(latest.get("requested_at", ""))[:19].replace("T", " ")
    print(
        f"Most recent run:   "
        f"{str(latest['run_id']):<20}  "
        f"{str(latest.get('capability') or ''):<16}  "
        f"{_normalize_status(latest.get('status', '')):<16}  "
        f"{latest_started}"
    )

    # Last failure (FAILED, CAPABILITY_ERROR, or TIMEOUT)
    last_failure = next(
        (r for r in all_rows if _normalize_status(r.get("status", "")) in _FAILURE_STATUSES),
        None,
    )
    if last_failure:
        fail_started = str(last_failure.get("requested_at", ""))[:19].replace("T", " ")
        print(
            f"Last failure:      "
            f"{str(last_failure['run_id']):<20}  "
            f"{str(last_failure.get('capability') or ''):<16}  "
            f"{_normalize_status(last_failure.get('status', '')):<16}  "
            f"{fail_started}"
        )

    return 0


def _resolve_run_shortcut(
    journal_dir: Path,
    latest: bool = False,
    last_failure: bool = False,
) -> tuple[str | None, str | None]:
    """Resolve --latest or --last-failure to a concrete run_id.

    Returns (run_id, None) on successful resolution.
    Returns (None, error_message) if the journal is empty or no match.
    Returns (None, None) if no shortcut is requested (caller handles positional).

    This is a pure lookup — no business logic, no journal mutation.
    """
    if not latest and not last_failure:
        return None, None

    try:
        rows = ExecutionJournal(journal_dir).list_runs(limit=10000)
    except Exception:
        rows = []

    if latest:
        if not rows:
            return None, "No runs found."
        return rows[0]["run_id"], None

    # last_failure
    match = next(
        (r for r in rows if _normalize_status(r.get("status", "")) in _FAILURE_STATUSES),
        None,
    )
    if match is None:
        return None, "No failed runs found."
    return match["run_id"], None


def cmd_runs(args: argparse.Namespace) -> int:
    """List recent execution runs, with optional status/capability filters."""
    project_root = find_project_root()
    journal = ExecutionJournal(project_root / ".agent_os" / "journal")
    limit = getattr(args, "limit", 10)
    status_filter = getattr(args, "status", None)
    capability_filter = getattr(args, "capability", None)
    show_summary = getattr(args, "summary", False)

    if show_summary:
        return _cmd_runs_summary(journal)

    # When filters are active, scan all rows then filter; otherwise use limit directly
    if status_filter or capability_filter:
        all_rows = journal.list_runs(limit=10000)
        rows = _filter_rows(all_rows, status_filter, capability_filter)
        rows = rows[:limit]
    else:
        rows = journal.list_runs(limit=limit)

    if not rows:
        print("No runs found.")
        return 0

    _print_runs_table(rows)
    return 0


def _find_spec_by_agent_id(project_root: Path, agent_id: str) -> Path | None:
    """Scan specs/ for a YAML file whose id field matches agent_id.

    Returns the first matching path, or None if not found.
    Failures in individual files are silently skipped.
    """
    import yaml

    specs_dir = project_root / "specs"
    if not specs_dir.exists():
        return None
    for path in sorted(specs_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            if isinstance(data, dict) and data.get("id") == agent_id:
                return path
        except Exception:
            continue
    return None


def _enrich_replay_record(
    journal_dir: Path, new_run_id: str, original_run_id: str
) -> None:
    """Inject replay linkage into the new journal entry. Non-fatal on error."""
    try:
        path = journal_dir / f"{new_run_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text())
        meta = data.get("metadata") or {}
        meta["replay_of_run_id"] = original_run_id
        meta["trigger"] = "operator_replay"
        data["metadata"] = meta
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _replay_run(
    run_id: str,
    project_root: Path,
    journal_dir: Path,
    adapter_factory: Any | None = None,
    registry_path: Path | None = None,
) -> tuple[dict, int]:
    """Core replay logic — separated for testability.

    Returns (result_dict, exit_code).
    result_dict includes "_new_run_id" and "_replay_of" on success.
    """
    if registry_path is None:
        registry_path = project_root / "capabilities" / "registry.yaml"
    if adapter_factory is None:
        adapter_factory = _default_adapter_factory

    # ── 1. Load original record ──────────────────────────────
    record_path = journal_dir / f"{run_id}.json"
    if not record_path.exists():
        return {"error": f"Run {run_id} not found."}, 1

    try:
        original = json.loads(record_path.read_text())
    except Exception as exc:
        return {"error": f"Run {run_id} not found."}, 1

    # ── 2. Extract replay context ────────────────────────────
    capability = original.get("capability")
    agent_id = original.get("agent_id")
    runtime_target = original.get("runtime_target")

    # ── 3. Validate replayability ────────────────────────────
    _NOT_REPLAYABLE = (
        f"Run {run_id} is not replayable. Missing required execution context."
    )
    if not capability or not agent_id or not runtime_target:
        return {"error": _NOT_REPLAYABLE}, 0

    # ── 4. Find spec by agent_id ─────────────────────────────
    spec_path = _find_spec_by_agent_id(project_root, agent_id)
    if spec_path is None:
        return {"error": _NOT_REPLAYABLE}, 0

    # ── 5. Boot chassis and execute ──────────────────────────
    chassis = Chassis(
        registry_path=registry_path,
        adapter_factory=adapter_factory,
        journal_dir=journal_dir,
    )
    report = chassis.boot(spec_path)
    if not report.success:
        return {"error": _NOT_REPLAYABLE}, 0

    result = chassis.execute_task(capability)
    new_run_id = result.get("run_id", "N/A")

    # ── 6. Enrich new journal entry with replay linkage ──────
    _enrich_replay_record(journal_dir, new_run_id, run_id)

    result["_replay_of"] = run_id
    result["_new_run_id"] = new_run_id
    return result, 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a prior run — creates a new run through the chassis.

    Accepts a positional run_id OR --last-failure to replay the most
    recent failed run.
    """
    project_root = find_project_root()
    journal_dir = project_root / ".agent_os" / "journal"

    use_last_failure = getattr(args, "last_failure", False)
    if use_last_failure:
        run_id, err = _resolve_run_shortcut(journal_dir, last_failure=True)
        if err:
            print(err)
            return 0
    else:
        run_id = getattr(args, "run_id", None)
        if not run_id:
            print("Provide a run_id or --last-failure.")
            return 1

    result, exit_code = _replay_run(
        run_id=run_id,
        project_root=project_root,
        journal_dir=journal_dir,
    )

    # ── Case 1: run not found ────────────────────────────────
    if exit_code == 1:
        print(result["error"])
        return 1

    # ── Case 2: not replayable (replay was never attempted) ──
    if "_new_run_id" not in result:
        print(result.get("error", f"Run {run_id} is not replayable."))
        return 0

    # ── Success / runtime result ─────────────────────────────
    new_run_id = result.get("_new_run_id", "N/A")
    status = result.get("status", "N/A")
    cap_used = result.get("capability_used", "N/A")
    output = result.get("output") or ""
    error = result.get("error") or ""
    lifecycle = result.get("lifecycle", [])

    print(f"Agent OS — replay")
    print(f"Original:   {run_id}")
    print(f"Run ID:     {new_run_id}")
    print(f"Status:     {status}")
    print(f"Capability: {cap_used}")

    if output:
        summary = (output[:120] + "...") if len(output) > 120 else output
        print(f"Result:     {summary}")
    if error:
        print(f"Error:      {error[:120]}")

    if lifecycle:
        print()
        print("Lifecycle:")
        for step in lifecycle:
            reason = f" ({step['reason']})" if step.get("reason") else ""
            print(f"  {step['from']} -> {step['to']}{reason}")

    print()
    print(f"Journal:    {new_run_id}.json written")
    print(f"            replay_of: {run_id}")

    return 0


_FAILURE_REASON_MAP: dict[str, str] = {
    "TIMEOUT":          "Runtime execution timed out",
    "FAILED":           "Runtime returned a failure result",
    "CAPABILITY_ERROR": "Capability not supported by runtime adapter",
}

_SUMMARY_WIDTH = 48


def _format_duration(started_at: str | None, finished_at: str | None) -> str:
    """Format elapsed time between two ISO timestamp strings."""
    if not started_at or not finished_at:
        return "unknown"
    try:
        from datetime import datetime as _dt
        def _parse(s: str) -> _dt:
            return _dt.fromisoformat(str(s).replace("Z", "+00:00"))
        delta = (_parse(finished_at) - _parse(started_at)).total_seconds()
        if delta < 0:
            delta = 0.0
        if delta < 60:
            return f"{delta:.1f}s"
        minutes = int(delta // 60)
        seconds = delta % 60
        return f"{minutes}m {seconds:.1f}s"
    except Exception:
        return "unknown"


def _print_failure_summary(data: dict) -> None:
    """Write a human-readable failure summary block to stderr before JSON stdout.

    Written to stderr so that stdout remains pure JSON (machine-parseable).
    Skipped entirely for SUCCESS runs. All missing fields are skipped
    gracefully — no KeyError or crash.
    """
    raw_status = data.get("status", "")
    norm = _normalize_status(raw_status)
    if norm not in _FAILURE_STATUSES:
        return

    reason = _FAILURE_REASON_MAP.get(norm, "Unknown failure")
    header = "── Failure Summary "

    def _out(line: str = "") -> None:
        print(line, file=sys.stderr)

    def _row(label: str, value: object) -> None:
        if value is not None and str(value).strip():
            _out(f"  {label:<13}{value}")

    _out(header + "─" * (_SUMMARY_WIDTH - len(header)))
    _row("Status:", norm)
    _row("Capability:", data.get("capability"))
    _row("Runtime:", data.get("runtime_target"))
    _row("Agent:", data.get("agent_id"))
    _out(f"  {'Duration:':<13}{_format_duration(data.get('started_at'), data.get('finished_at'))}")
    _out(f"  {'Reason:':<13}{reason}")
    _row("Error:", data.get("error_message"))
    _row("Policy:", data.get("policy_decision"))
    _out("─" * _SUMMARY_WIDTH)
    _out()


def cmd_inspect(args: argparse.Namespace) -> int:
    """Print the full journal record for a specific run_id as pretty-printed JSON.

    Accepts a positional run_id OR one of:
      --latest        resolve to the most recent run
      --last-failure  resolve to the most recent failed run
    """
    project_root = find_project_root()
    journal_dir = project_root / ".agent_os" / "journal"

    use_latest = getattr(args, "latest", False)
    use_last_failure = getattr(args, "last_failure", False)

    if use_latest or use_last_failure:
        run_id, err = _resolve_run_shortcut(
            journal_dir, latest=use_latest, last_failure=use_last_failure
        )
        if err:
            print(err)
            return 0
    else:
        run_id = getattr(args, "run_id", None)
        if not run_id:
            print("Provide a run_id, --latest, or --last-failure.")
            return 1

    # ── Existing inspect path (unchanged) ────────────────────
    record_path = journal_dir / f"{run_id}.json"

    if not record_path.exists():
        print(f"Run {run_id} not found.")
        return 1

    try:
        data = json.loads(record_path.read_text())
        _print_failure_summary(data)
        print(json.dumps(data, indent=2))
        return 0
    except Exception:
        print(f"Run {run_id} not found.")
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="Agent OS — runtime-agnostic agent chassis",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run command
    run_parser = subparsers.add_parser("run", help="Run a capability through the sandbox chassis")
    run_parser.add_argument("spec", help="Path to agent spec YAML")
    run_parser.add_argument("capability", help="Capability ID to execute (e.g. web.search)")
    run_parser.add_argument("--registry", help="Path to capability registry YAML")

    # boot command
    boot_parser = subparsers.add_parser("boot", help="Boot an agent through the chassis")
    boot_parser.add_argument("spec", help="Path to agent spec YAML")
    boot_parser.add_argument("--registry", help="Path to capability registry YAML")

    # journal command
    journal_parser = subparsers.add_parser("journal", help="Inspect execution journal")
    journal_sub = journal_parser.add_subparsers(dest="journal_command")
    journal_sub.add_parser("latest", help="Show the most recent run journal entry")

    # runs command
    runs_parser = subparsers.add_parser("runs", help="List recent execution runs")
    runs_parser.add_argument("--limit", type=int, default=10, help="Max runs to show (default 10)")
    runs_parser.add_argument("--status", help="Filter by status (success|failed|capability_error|timeout)")
    runs_parser.add_argument("--capability", help="Filter by capability (e.g. web.search)")
    runs_parser.add_argument("--summary", action="store_true", default=False, help="Show aggregate summary")

    # inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Show full journal record for a run_id")
    inspect_parser.add_argument("run_id", nargs="?", help="Run ID to inspect")
    inspect_parser.add_argument("--latest", action="store_true", default=False,
                                help="Inspect the most recent run")
    inspect_parser.add_argument("--last-failure", action="store_true", default=False,
                                dest="last_failure",
                                help="Inspect the most recent failed run")

    # replay command
    replay_parser = subparsers.add_parser("replay", help="Replay a prior run by run_id")
    replay_parser.add_argument("run_id", nargs="?", help="Run ID to replay")
    replay_parser.add_argument("--last-failure", action="store_true", default=False,
                               dest="last_failure",
                               help="Replay the most recent failed run")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "boot":
        sys.exit(cmd_boot(args))
    elif args.command == "journal":
        if getattr(args, "journal_command", None) == "latest":
            sys.exit(cmd_journal_latest(args))
        else:
            journal_parser.print_help()
            sys.exit(1)
    elif args.command == "runs":
        sys.exit(cmd_runs(args))
    elif args.command == "inspect":
        sys.exit(cmd_inspect(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
