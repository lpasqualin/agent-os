"""Agent OS CLI — the interface to the chassis.

Usage:
    agent-os boot <spec_path> [--registry <registry_path>]
    python -m agent_os.cli boot specs/clawbot.agent.yaml
"""

import argparse
import sys
from pathlib import Path

from agent_os.chassis import Chassis
from agent_os.adapters.runtime.mock_runtime import MockRuntime
from agent_os.adapters.runtime.openclaw_runtime import OpenClawRuntime


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

    args = parser.parse_args()

    if args.command == "boot":
        sys.exit(cmd_boot(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
