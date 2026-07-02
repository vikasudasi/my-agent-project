"""Tests for MCP server instructions."""

from mcp_instructions import MCP_INSTRUCTIONS


def test_mcp_instructions_covers_key_workflows():
    assert "agent_onboard" in MCP_INSTRUCTIONS
    assert "project_snapshot" in MCP_INSTRUCTIONS
    assert "doc_task_get" in MCP_INSTRUCTIONS
    assert "## Objective" in MCP_INSTRUCTIONS
    assert "project_archive" in MCP_INSTRUCTIONS
    assert "blocker_reason" in MCP_INSTRUCTIONS
    assert len(MCP_INSTRUCTIONS) >= 1500


def test_mcp_instructions_is_trimmed():
    assert MCP_INSTRUCTIONS == MCP_INSTRUCTIONS.strip()
