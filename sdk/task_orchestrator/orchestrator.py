"""Orchestrator main loop."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from task_orchestrator.backends.tm_base import TaskManagerBackend
from task_orchestrator.backends.tm_cli import CliBackend
from task_orchestrator.config import OrchestratorConfig
from task_orchestrator.prompt import build_prompt
from task_orchestrator.runners.base import AgentRunner
from task_orchestrator.runners.cursor_cli import CursorCliRunner
from task_orchestrator.traversal import get_work_units


@dataclass
class StepResult:
    task_id: str
    status: str
    exit_code: int | None = None
    log_path: str | None = None
    error: str | None = None


@dataclass
class RunResult:
    run_id: str
    root_task_id: str
    status: str
    steps: list[StepResult] = field(default_factory=list)
    run_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "root_task_id": self.root_task_id,
            "status": self.status,
            "run_dir": self.run_dir,
            "steps": [s.__dict__ for s in self.steps],
        }


class Orchestrator:
    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        tm: TaskManagerBackend | None = None,
        runner: AgentRunner | None = None,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.tm = tm or self._default_tm()
        self.runner = runner or CursorCliRunner(config.agent)
        self.dry_run = dry_run

    def _default_tm(self) -> TaskManagerBackend:
        if self.config.tm.backend != "cli":
            raise NotImplementedError(f"TM backend '{self.config.tm.backend}' not implemented in Phase 1")
        return CliBackend(
            cli_path=self.config.tm.cli_path or None,
            server_dir=self.config.tm.server_dir or None,
            api_key=self.config.api_key(),
        )

    def run(self, root_task_id: str) -> RunResult:
        run_id = uuid.uuid4().hex[:12]
        run_dir = Path(self.config.runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        policies = self.config.policies
        tree = self.tm.get_task_tree(root_task_id)
        units = get_work_units(tree, policies.traversal, policies.skip_statuses)

        result = RunResult(
            run_id=run_id,
            root_task_id=root_task_id,
            status="running",
            run_dir=str(run_dir),
        )

        self._write_manifest(run_dir, root_task_id, units)

        for task_id in units:
            step = self._run_step(task_id, run_dir)
            result.steps.append(step)

            if step.status == "blocked":
                result.status = "paused"
                break
            if step.status == "failed":
                if policies.on_failure == "continue":
                    continue
                result.status = "paused" if policies.on_failure == "stop" else "failed"
                break
        else:
            result.status = "completed"
            if policies.auto_complete_parent and units:
                self._maybe_complete_parent(root_task_id, tree)

        self._write_summary(run_dir, result)
        return result

    def _run_step(self, task_id: str, run_dir: Path) -> StepResult:
        policies = self.config.policies
        task = self.tm.get_task(task_id)

        if task.get("status") == "blocked":
            return StepResult(task_id=task_id, status="blocked", error="Task is blocked")

        log_path = run_dir / f"step_{task_id}.log"
        prompt = build_prompt(task_id, self.config.repeat_instructions)

        if policies.status_mode == "sdk":
            self.tm.update_task_status(task_id, "in_progress")

        if self.dry_run:
            log_path.write_text(f"=== DRY RUN ===\n{prompt}\n", encoding="utf-8")
            return StepResult(task_id=task_id, status="skipped", log_path=str(log_path))

        agent_result = self.runner.run(prompt, log_path=log_path)

        if agent_result.exit_code != 0 or agent_result.timed_out:
            if policies.status_mode == "sdk":
                self.tm.update_task_status(task_id, "failed")
            return StepResult(
                task_id=task_id,
                status="failed",
                exit_code=agent_result.exit_code,
                log_path=str(log_path),
                error="Agent exited non-zero" if not agent_result.timed_out else "Agent timed out",
            )

        if policies.status_mode == "sdk":
            self.tm.update_task_status(task_id, "completed")
        elif policies.verify_completion:
            updated = self.tm.get_task(task_id)
            if updated.get("status") != "completed":
                return StepResult(
                    task_id=task_id,
                    status="failed",
                    exit_code=agent_result.exit_code,
                    log_path=str(log_path),
                    error=f"Task status is '{updated.get('status')}', expected 'completed'",
                )

        return StepResult(
            task_id=task_id,
            status="completed",
            exit_code=agent_result.exit_code,
            log_path=str(log_path),
        )

    def _maybe_complete_parent(self, root_task_id: str, tree: dict) -> None:
        children = tree.get("children") or []
        if not children:
            return
        if self.config.policies.status_mode != "sdk":
            return
        for child in children:
            current = self.tm.get_task(child["id"])
            if current.get("status") not in ("completed", "cancelled"):
                return
        self.tm.update_task_status(root_task_id, "completed")

    @staticmethod
    def _write_manifest(run_dir: Path, root_task_id: str, units: list[str]) -> None:
        manifest = {
            "root_task_id": root_task_id,
            "units": units,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @staticmethod
    def _write_summary(run_dir: Path, result: RunResult) -> None:
        (run_dir / "summary.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
