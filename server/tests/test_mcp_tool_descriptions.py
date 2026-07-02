"""Tests for workflow-oriented MCP tool descriptions."""

import asyncio

import mcp_server
from mcp_tool_descriptions import TOOL_DESCRIPTIONS


EXPECTED_TOOLS = {
    "agent_onboard",
    "agent_list",
    "audit_log_get",
    "comment_add",
    "comment_list",
    "doc_project_get",
    "doc_project_update",
    "doc_task_get",
    "doc_task_update",
    "project_archive",
    "project_create",
    "project_delete",
    "project_get",
    "project_list",
    "project_restore",
    "project_snapshot",
    "project_update",
    "session_context",
    "task_begin_work",
    "task_complete",
    "task_create",
    "task_delete",
    "task_get",
    "task_list",
    "task_move",
    "task_record_progress",
    "task_subtree",
    "task_tree",
    "task_update",
}


def test_all_tools_have_descriptions():
    assert set(TOOL_DESCRIPTIONS) == EXPECTED_TOOLS


def test_descriptions_are_workflow_oriented():
    for name, desc in TOOL_DESCRIPTIONS.items():
        assert len(desc) >= 80, f"{name} description too short"
        assert desc == desc.strip()


def test_key_tools_mention_workflow_triggers():
    assert "session-start" in TOOL_DESCRIPTIONS["project_snapshot"].lower()
    assert "in_progress" in TOOL_DESCRIPTIONS["task_update"]
    assert "closure" in TOOL_DESCRIPTIONS["doc_task_update"].lower()
    assert "project_archive" in TOOL_DESCRIPTIONS["project_delete"]


def test_list_tools_uses_descriptions():
    tools = asyncio.run(mcp_server.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description == TOOL_DESCRIPTIONS[tool.name]
