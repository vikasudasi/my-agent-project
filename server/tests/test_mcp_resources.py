"""Tests for static MCP resources (playbook and templates)."""

import asyncio

import mcp_server
from mcp_resources import (
    CLOSURE_TEMPLATE_URI,
    PLAYBOOK_URI,
    PROGRESS_TEMPLATE_URI,
    SPEC_TEMPLATE_URI,
    STATIC_RESOURCE_URIS,
    read_static_resource,
    list_static_resources,
)
from mcp_instructions import MCP_INSTRUCTIONS


def test_static_resource_uris():
    assert len(STATIC_RESOURCE_URIS) == 4
    assert PLAYBOOK_URI in STATIC_RESOURCE_URIS
    assert SPEC_TEMPLATE_URI in STATIC_RESOURCE_URIS


def test_list_static_resources():
    resources = list_static_resources()
    assert len(resources) == 4
    uris = {str(r.uri) for r in resources}
    assert uris == STATIC_RESOURCE_URIS
    for resource in resources:
        assert resource.mimeType == "text/markdown"
        assert resource.description


def test_playbook_includes_instructions_and_resource_index():
    contents = list(read_static_resource(PLAYBOOK_URI))
    assert len(contents) == 1
    text = contents[0].content
    assert MCP_INSTRUCTIONS in text
    assert "taskmgr://templates/spec" in text


def test_spec_template_has_required_sections():
    text = list(read_static_resource(SPEC_TEMPLATE_URI))[0].content
    assert "## Objective" in text
    assert "## Acceptance Criteria" in text
    assert "initial_spec" in text


def test_progress_template_mentions_progress_doc():
    text = list(read_static_resource(PROGRESS_TEMPLATE_URI))[0].content
    assert "## Status" in text
    assert "task_record_progress" in text


def test_closure_template_has_summary_section():
    text = list(read_static_resource(CLOSURE_TEMPLATE_URI))[0].content
    assert "## Summary" in text
    assert "task_complete" in text


def test_unknown_uri_raises():
    try:
        list(read_static_resource("taskmgr://unknown/resource"))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Unknown resource URI" in str(exc)


def test_mcp_server_registers_resources():
    resources = asyncio.run(mcp_server.list_resources())
    assert len(resources) == 4


def test_mcp_server_read_resource_playbook():
    contents = asyncio.run(mcp_server.read_resource(PLAYBOOK_URI))
    assert len(contents) == 1
    assert contents[0].mime_type == "text/markdown"
    assert "session_context" in contents[0].content
