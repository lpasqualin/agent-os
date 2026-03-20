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


def cmd_runs(args: argparse.Namespace) -> int:
    """List recent execution runs."""
    project_root = find_project_root()
    journal = ExecutionJournal(project_root / ".agent_os" / "journal")
    limit = getattr(args, "limit", 10)
    rows = journal.list_runs(limit=limit)

    if not rows:
        print("No runs found.")
        return 0

    header = f"{'RUN_ID':<20}  {'CAPABILITY':<16}  {'STATUS':<14}  STARTED_AT"
    print()
    print(header)
    print("-" * len(header))
    for r in rows:
        started = str(r.get("requested_at", ""))[:19].replace("T", " ")
        print(
            f"{str(r['run_id']):<20}  "
            f"{str(r['capability'] or ''):<16}  "
            f"{str(r['status']):<14}  "
            f"{started}"
        )
    print()
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
    """Replay a prior run by run_id — creates a new run through the chassis."""
    project_root = find_project_root()
    journal_dir = project_root / ".agent_os" / "journal"
    run_id = args.run_id

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


def cmd_inspect(args: argparse.Namespace) -> int:
    """Print the full journal record for a specific run_id as pretty-printed JSON."""
    project_root = find_project_root()
    journal_dir = project_root / ".agent_os" / "journal"
    run_id = args.run_id
    record_path = journal_dir / f"{run_id}.json"

    if not record_path.exists():
        print(f"Run {run_id} not found.")
        return 1

    try:
        data = json.loads(record_path.read_text())
        print(json.dumps(data, indent=2))
        return 0
    except Exception as exc:
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

    # inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Show full journal record for a run_id")
    inspect_parser.add_argument("run_id", help="Run ID to inspect")

    # replay command
    replay_parser = subparsers.add_parser("replay", help="Replay a prior run by run_id")
    replay_parser.add_argument("run_id", help="Run ID to replay")

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
