"""Headless agent runner interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentResult:
    exit_code: int
    stdout: str
    stderr: str
    log_path: Path | None = None
    timed_out: bool = False


class AgentRunner(ABC):
    @abstractmethod
    def run(self, prompt: str, *, log_path: Path) -> AgentResult:
        """Invoke the headless agent with the given prompt."""
