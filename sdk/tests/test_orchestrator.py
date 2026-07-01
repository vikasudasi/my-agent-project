from pathlib import Path

import pytest

from task_orchestrator.backends.tm_base import TaskManagerBackend
from task_orchestrator.config import OrchestratorConfig, PoliciesConfig
from task_orchestrator.orchestrator import Orchestrator
from task_orchestrator.runners.base import AgentResult, AgentRunner


class FakeTm(TaskManagerBackend):
    def __init__(self, tree: dict, statuses: dict[str, str] | None = None):
        self.tree = tree
        self.statuses = statuses or {}

    def get_task_tree(self, task_id: str) -> dict:
        return self.tree

    def get_task(self, task_id: str) -> dict:
        status = self.statuses.get(task_id, "pending")
        return {"id": task_id, "status": status}

    def update_task_status(self, task_id: str, status: str) -> dict:
        self.statuses[task_id] = status
        return {"id": task_id, "status": status}


class FakeRunner(AgentRunner):
    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code
        self.prompts: list[str] = []

    def run(self, prompt: str, *, log_path: Path) -> AgentResult:
        self.prompts.append(prompt)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(prompt, encoding="utf-8")
        return AgentResult(exit_code=self.exit_code, stdout="ok", stderr="", log_path=log_path)


@pytest.fixture
def simple_tree():
    return {
        "id": "root",
        "status": "pending",
        "children": [
            {"id": "s1", "status": "pending", "children": []},
            {"id": "s2", "status": "pending", "children": []},
        ],
    }


def test_orchestrator_dry_run(simple_tree, tmp_path):
    config = OrchestratorConfig(runs_dir=str(tmp_path / "runs"))
    config.repeat_instructions = "Repeat me."
    tm = FakeTm(simple_tree)
    orch = Orchestrator(config, tm=tm, runner=FakeRunner(), dry_run=True)
    result = orch.run("root")

    assert result.status == "completed"
    assert len(result.steps) == 2
    assert all(s.status == "skipped" for s in result.steps)
    assert (tmp_path / "runs" / result.run_id / "manifest.json").exists()


class CompletingRunner(AgentRunner):
    def __init__(self, tm: FakeTm, exit_code: int = 0):
        self.tm = tm
        self.exit_code = exit_code
        self.prompts: list[str] = []

    def run(self, prompt: str, *, log_path: Path) -> AgentResult:
        self.prompts.append(prompt)
        for tid in ("s1", "s2"):
            if tid in prompt:
                self.tm.statuses[tid] = "completed"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(prompt, encoding="utf-8")
        return AgentResult(exit_code=self.exit_code, stdout="ok", stderr="", log_path=log_path)


def test_orchestrator_completes_when_agent_updates_tm(simple_tree, tmp_path):
    config = OrchestratorConfig(runs_dir=str(tmp_path / "runs"))
    tm = FakeTm(simple_tree)
    runner = CompletingRunner(tm)

    orch = Orchestrator(config, tm=tm, runner=runner)
    result = orch.run("root")

    assert result.status == "completed"
    assert len(runner.prompts) == 2
    assert "s1" in runner.prompts[0]
    assert "s2" in runner.prompts[1]


def test_orchestrator_fails_when_task_not_completed(simple_tree, tmp_path):
    config = OrchestratorConfig(runs_dir=str(tmp_path / "runs"))
    tm = FakeTm(simple_tree)
    orch = Orchestrator(config, tm=tm, runner=FakeRunner(exit_code=0))
    result = orch.run("root")

    assert result.status == "paused"
    assert result.steps[0].status == "failed"
    assert "expected 'completed'" in (result.steps[0].error or "")


def test_orchestrator_sdk_status_mode(simple_tree, tmp_path):
    config = OrchestratorConfig(runs_dir=str(tmp_path / "runs"))
    config.policies = PoliciesConfig(status_mode="sdk", verify_completion=False, auto_complete_parent=True)
    tm = FakeTm(simple_tree)
    orch = Orchestrator(config, tm=tm, runner=FakeRunner(exit_code=0))
    result = orch.run("root")

    assert result.status == "completed"
    assert tm.statuses["s1"] == "completed"
    assert tm.statuses["s2"] == "completed"
    assert tm.statuses["root"] == "completed"
