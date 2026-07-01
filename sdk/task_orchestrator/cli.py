#!/usr/bin/env python3
"""CLI entry point for the task orchestrator SDK."""

from __future__ import annotations

import argparse
import json
import sys

from task_orchestrator.config import load_config
from task_orchestrator.orchestrator import Orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate sequential subtask execution via headless CLI agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run subtasks under a root task ID")
    run_parser.add_argument("--task", required=True, help="Root task ID")
    run_parser.add_argument("--config", required=True, help="Path to orchestrator YAML config")
    run_parser.add_argument("--dry-run", action="store_true", help="Plan steps and write prompts without invoking agent")
    run_parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print JSON result")

    list_parser = sub.add_parser("plan", help="List work units without running agents")
    list_parser.add_argument("--task", required=True, help="Root task ID")
    list_parser.add_argument("--config", required=True, help="Path to orchestrator YAML config")
    list_parser.add_argument("--pretty", "-p", action="store_true")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "plan":
        from task_orchestrator.backends.tm_cli import CliBackend
        from task_orchestrator.traversal import get_work_units

        tm = CliBackend(
            cli_path=config.tm.cli_path or None,
            server_dir=config.tm.server_dir or None,
            api_key=config.api_key(),
        )
        tree = tm.get_task_tree(args.task)
        units = get_work_units(tree, config.policies.traversal, config.policies.skip_statuses)
        out = {"root_task_id": args.task, "units": units, "count": len(units)}
        print(json.dumps(out, indent=2 if args.pretty else None))
        return 0

    orch = Orchestrator(config, dry_run=args.dry_run)
    result = orch.run(args.task)
    print(json.dumps(result.to_dict(), indent=2 if args.pretty else None))

    if result.status == "completed":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
