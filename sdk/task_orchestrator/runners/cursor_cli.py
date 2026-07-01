"""Cursor CLI headless agent runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

from task_orchestrator.config import AgentConfig
from task_orchestrator.runners.base import AgentResult, AgentRunner


class CursorCliRunner(AgentRunner):
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def run(self, prompt: str, *, log_path: Path) -> AgentResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [self.config.command, *self.config.args]

        if self.config.prompt_via == "stdin":
            input_data = prompt
            cmd_for_run = cmd
        else:
            input_data = None
            cmd_for_run = [*cmd, prompt]

        try:
            result = subprocess.run(
                cmd_for_run,
                input=input_data,
                capture_output=True,
                text=True,
                cwd=self.config.cwd,
                timeout=self.config.timeout_seconds,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            self._write_log(log_path, prompt, stdout, stderr, exit_code=-1, timed_out=True)
            return AgentResult(exit_code=-1, stdout=stdout, stderr=stderr, log_path=log_path, timed_out=True)

        self._write_log(log_path, prompt, result.stdout, result.stderr, result.returncode, timed_out)
        return AgentResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            log_path=log_path,
            timed_out=timed_out,
        )

    @staticmethod
    def _write_log(
        log_path: Path,
        prompt: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        timed_out: bool,
    ) -> None:
        with log_path.open("w", encoding="utf-8") as f:
            f.write("=== PROMPT ===\n")
            f.write(prompt)
            f.write("\n\n=== STDOUT ===\n")
            f.write(stdout)
            f.write("\n\n=== STDERR ===\n")
            f.write(stderr)
            f.write(f"\n\n=== EXIT CODE ===\n{exit_code}\n")
            if timed_out:
                f.write("\n=== TIMED OUT ===\n")
