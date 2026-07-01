"""Task manager CLI backend — subprocess wrapper around server/cli.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from task_orchestrator.backends.tm_base import TaskManagerBackend


class CliBackend(TaskManagerBackend):
    def __init__(
        self,
        *,
        cli_path: str | None = None,
        server_dir: str | None = None,
        api_key: str | None = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.server_dir = Path(server_dir or repo_root / "server")
        self.cli_path = Path(cli_path or self.server_dir / "cli.py")
        self.api_key = api_key
        self._python = sys.executable

    def _run(self, *args: str, require_auth: bool = False) -> Any:
        cmd = [self._python, str(self.cli_path), *args]
        env = os.environ.copy()
        if require_auth:
            key = self.api_key or os.environ.get("TM_API_KEY")
            if not key:
                raise RuntimeError("TM_API_KEY required for this operation")
            env["TM_API_KEY"] = key

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.server_dir),
            env=env,
        )
        if result.returncode != 0:
            try:
                err = json.loads(result.stderr.strip() or result.stdout.strip())
            except json.JSONDecodeError:
                err = {"error": result.stderr.strip() or result.stdout.strip() or "CLI failed"}
            raise RuntimeError(err.get("error", err))

        return json.loads(result.stdout)

    def get_task_tree(self, task_id: str) -> dict[str, Any]:
        data = self._run("task", "tree", task_id)
        if not data:
            raise RuntimeError(f"Task not found: {task_id}")
        return data

    def get_task(self, task_id: str) -> dict[str, Any]:
        data = self._run("task", "get", task_id)
        if not data:
            raise RuntimeError(f"Task not found: {task_id}")
        return data

    def update_task_status(self, task_id: str, status: str) -> dict[str, Any]:
        return self._run("task", "update", task_id, "--status", status, require_auth=True)
