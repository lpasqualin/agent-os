"""Agent OS CLI — the interface to the chassis.

Usage:
    agent-os boot <spec_path> [--registry <registry_path>]
    agent-os journal latest
    agent-os runs [--limit N]
    python -m agent_os.cli boot specs/clawbot.agent.yaml
"""

import argparse
import sys
from pathlib import Path

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


def cmd_journal_latest(args: argparse.Namespace) -> int:
    """Print the most recent journal entry."""
    project_root = find_project_root()
    journal = ExecutionJournal(project_root / ".agent_os" / "journal")
    record = journal.read_latest()

    if record is None:
        print("No journal entries found.")
        return 0

    print()
    print("=" * 60)
    print("  Latest Execution Journal Entry")
    print("=" * 60)
    print(f"  Run ID:          {record.run_id}")
    print(f"  Journal ID:      {record.journal_id}")
    print(f"  Agent:           {record.agent_id}")
    print(f"  Capability:      {record.capability or 'N/A'}")
    print(f"  Runtime target:  {record.runtime_target or 'N/A'}")
    print(f"  Status:          {record.status}")
    print(f"  Policy decision: {record.policy_decision or 'N/A'}")
    print(f"  Requested at:    {record.requested_at}")
    if record.started_at:
        print(f"  Started at:      {record.started_at}")
    print(f"  Finished at:     {record.finished_at}")
    if record.metadata.get("duration_ms") is not None:
        print(f"  Duration:        {record.metadata['duration_ms']} ms")
    if record.result_summary:
        summary = record.result_summary
        if len(summary) > 120:
            summary = summary[:117] + "..."
        print(f"  Output summary:  {summary}")
    if record.error_type:
        print(f"  Error type:      {record.error_type}")
    if record.error_message:
        msg = record.error_message
        if len(msg) > 120:
            msg = msg[:117] + "..."
        print(f"  Error message:   {msg}")
    if record.lifecycle_trace:
        print()
        print("  Lifecycle:")
        for step in record.lifecycle_trace:
            reason = f" ({step['reason']})" if step.get("reason") else ""
            print(f"    {step['from']} -> {step['to']}{reason}")
    print()
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """List recent execution runs."""
    project_root = find_project_root()
    journal = ExecutionJournal(project_root / ".agent_os" / "journal")
    limit = getattr(args, "limit", 20)
    rows = journal.list_runs(limit=limit)

    if not rows:
        print("No runs recorded yet.")
        return 0

    header = f"{'RUN_ID':<16}  {'STATUS':<12}  {'AGENT':<20}  {'CAPABILITY':<20}  REQUESTED_AT"
    print()
    print(header)
    print("-" * len(header))
    for r in rows:
        requested = str(r["requested_at"])[:19].replace("T", " ")
        print(
            f"{str(r['run_id']):<16}  "
            f"{str(r['status']):<12}  "
            f"{str(r['agent_id']):<20}  "
            f"{str(r['capability'] or ''):<20}  "
            f"{requested}"
        )
    print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="Agent OS — runtime-agnostic agent chassis",
    )
    subparsers = parser.add_subparsers(dest="command")

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
    runs_parser.add_argument("--limit", type=int, default=20, help="Max runs to show (default 20)")

    args = parser.parse_args()

    if args.command == "boot":
        sys.exit(cmd_boot(args))
    elif args.command == "journal":
        if getattr(args, "journal_command", None) == "latest":
            sys.exit(cmd_journal_latest(args))
        else:
            journal_parser.print_help()
            sys.exit(1)
    elif args.command == "runs":
        sys.exit(cmd_runs(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
