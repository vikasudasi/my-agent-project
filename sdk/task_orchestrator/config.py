"""Load orchestrator YAML configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TmConfig:
    backend: str = "cli"
    cli_path: str = ""
    server_dir: str = ""
    url: str = ""
    api_key_env: str = "TM_API_KEY"


@dataclass
class AgentConfig:
    command: str = "cursor"
    args: list[str] = field(default_factory=lambda: ["agent", "--print", "--force", "--output-format", "text"])
    cwd: str = "."
    timeout_seconds: int = 1800
    prompt_via: str = "arg"  # arg | stdin


@dataclass
class PoliciesConfig:
    traversal: str = "depth_first"
    on_failure: str = "stop"
    status_mode: str = "agent"
    auto_complete_parent: bool = True
    skip_statuses: list[str] = field(default_factory=lambda: ["completed", "cancelled"])
    verify_completion: bool = True


@dataclass
class OrchestratorConfig:
    tm: TmConfig = field(default_factory=TmConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    repeat_instructions: str = ""
    policies: PoliciesConfig = field(default_factory=PoliciesConfig)
    runs_dir: str = ".tm-runs"

    def api_key(self) -> str | None:
        return os.environ.get(self.tm.api_key_env) or None


def _merge_dataclass(cls: type, data: dict[str, Any] | None) -> Any:
    if not data:
        return cls()
    fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return cls(**{k: v for k, v in data.items() if k in fields})


def load_config(path: str | Path) -> OrchestratorConfig:
    """Load orchestrator config from a YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")

    return OrchestratorConfig(
        tm=_merge_dataclass(TmConfig, raw.get("tm")),
        agent=_merge_dataclass(AgentConfig, raw.get("agent")),
        repeat_instructions=(raw.get("repeat_instructions") or "").strip(),
        policies=_merge_dataclass(PoliciesConfig, raw.get("policies")),
        runs_dir=raw.get("runs_dir") or ".tm-runs",
    )
