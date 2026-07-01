"""Task manager backend interface (orchestration only)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TaskManagerBackend(ABC):
    @abstractmethod
    def get_task_tree(self, task_id: str) -> dict[str, Any]:
        """Return task node with nested children."""

    @abstractmethod
    def get_task(self, task_id: str) -> dict[str, Any]:
        """Return a single task record."""

    @abstractmethod
    def update_task_status(self, task_id: str, status: str) -> dict[str, Any]:
        """Update task status (used when status_mode is sdk)."""
