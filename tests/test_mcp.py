"""Unit tests for MCP tool privilege scoping and classification.

The tests verify that:

* tool names are prefixed ``mcp_<server>__<tool>`` and the server can be
  recovered from a prefixed name,
* servers are classified as sensitive or read-only,
* the agent-facing names of sensitive/read-only tools are collected
  correctly from a tool list,
* ``apply_mcp_tool_prefixes`` renames tools in place and preserves the
  original name on ``tool.metadata``,
* ``${VAR}`` references in config values are expanded from the environment.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from langchain.tools import BaseTool
from pydantic import Field
from typing_extensions import override

from berg_agents.config.mcp import (
    MCP_TOOL_PREFIX,
    READONLY_SERVERS,
    SENSITIVE_SERVERS,
    SERVER_SEP,
    apply_mcp_tool_prefixes,
    expand_env_vars,
    is_readonly_server,
    is_sensitive_server,
    prefix_tool_name,
    readonly_mcp_tool_names,
    sensitive_mcp_tool_names,
    server_from_prefixed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _GithubTool(BaseTool):
    """A tool that looks like it came from the ``github`` MCP server.

    Attributes:
        name (str): The prefixed tool name.
        description (str): A description of the tool.
    """

    name: str = prefix_tool_name("github", "create_issue")
    description: str = "Create a GitHub issue"

    @override
    def _run(self, title: str) -> str:
        """Run the tool.

        :param title: The issue title.
        :return: A confirmation string.
        """
        return f"created {title}"


class _CodegraphTool(BaseTool):
    """A tool that looks like it came from the ``codegraph`` MCP server.

    Attributes:
        name (str): The prefixed tool name.
        description (str): A description of the tool.
    """

    name: str = prefix_tool_name("codegraph", "explore")
    description: str = "Explore the codebase"

    @override
    def _run(self, query: str) -> str:
        """Run the tool.

        :param query: The query.
        :return: Exploration results.
        """
        return f"results for {query}"


class _ListFilesTool(BaseTool):
    """A plain tool used to exercise ``apply_mcp_tool_prefixes``.

    Attributes:
        name (str): The tool name.
        description (str): A description of the tool.
        metadata (dict): Tool metadata, pre-populated so the rename can
            record the original name.
    """

    name: str = "list_files"
    description: str = "List files"
    metadata: dict[str, Any] | None = Field(default_factory=dict)

    @override
    def _run(self) -> str:
        """Run the tool.

        :return: A file listing.
        """
        return "files"


@pytest.fixture
def github_tool() -> BaseTool:
    """A github-sourced MCP tool.

    :return: The tool.
    """
    return _GithubTool()


@pytest.fixture
def codegraph_tool() -> BaseTool:
    """A codegraph-sourced MCP tool.

    :return: The tool.
    """
    return _CodegraphTool()


# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------


def test_prefix_tool_name_format() -> None:
    """Prefixed names must follow ``mcp_<server>__<tool>``.

    :return: None
    :raises AssertionError: If the prefixed name is not well-formed.
    """
    name = prefix_tool_name("github", "create_issue")
    assert name == f"{MCP_TOOL_PREFIX}_github{SERVER_SEP}create_issue"


def test_server_from_prefixed_round_trip() -> None:
    """The server must be recoverable from a prefixed name.

    :return: None
    :raises AssertionError: If the server is not recovered.
    """
    name = prefix_tool_name("github", "create_issue")
    assert server_from_prefixed(name) == "github"


def test_server_from_prefixed_returns_none_for_unprefixed() -> None:
    """Unprefixed tool names must yield ``None``.

    :return: None
    :raises AssertionError: If a server is returned for an unprefixed name.
    """
    assert server_from_prefixed("read_file") is None


# ---------------------------------------------------------------------------
# Server classification
# ---------------------------------------------------------------------------


def test_sensitive_servers_are_disjoint_from_readonly() -> None:
    """A server must never be both sensitive and read-only.

    :return: None
    :raises AssertionError: If the server sets overlap.
    """
    assert SENSITIVE_SERVERS.isdisjoint(READONLY_SERVERS)


def test_is_sensitive_server_known_and_unknown() -> None:
    """Only servers in :data:`SENSITIVE_SERVERS` classify as sensitive.

    :return: None
    :raises AssertionError: If classification is wrong.
    """
    assert is_sensitive_server("github")
    assert is_sensitive_server("memory")
    assert not is_sensitive_server("codegraph")
    assert not is_sensitive_server("unknown-server")


def test_is_readonly_server_known_and_unknown() -> None:
    """Only servers in :data:`READONLY_SERVERS` classify as read-only.

    :return: None
    :raises AssertionError: If classification is wrong.
    """
    assert is_readonly_server("codegraph")
    assert is_readonly_server("context7")
    assert not is_readonly_server("github")
    assert not is_readonly_server("unknown-server")


# ---------------------------------------------------------------------------
# Tool-name collection
# ---------------------------------------------------------------------------


def test_sensitive_mcp_tool_names_collects_gated_tools(
    github_tool: BaseTool, codegraph_tool: BaseTool
) -> None:
    """Only tools from sensitive servers must be collected.

    :param github_tool: A github-sourced tool.
    :param codegraph_tool: A codegraph-sourced tool.
    :return: None
    :raises AssertionError: If the collected names are wrong.
    """
    names = sensitive_mcp_tool_names([github_tool, codegraph_tool])
    assert names == [github_tool.name]


def test_readonly_mcp_tool_names_collects_autonomous_tools(
    github_tool: BaseTool, codegraph_tool: BaseTool
) -> None:
    """Only tools from read-only servers must be collected.

    :param github_tool: A github-sourced tool.
    :param codegraph_tool: A codegraph-sourced tool.
    :return: None
    :raises AssertionError: If the collected names are wrong.
    """
    names = readonly_mcp_tool_names([github_tool, codegraph_tool])
    assert names == [codegraph_tool.name]


def test_collection_ignores_unprefixed_tools(github_tool: BaseTool) -> None:
    """Unprefixed tools must never be collected as MCP tools.

    :param github_tool: A github-sourced tool.
    :return: None
    :raises AssertionError: If an unprefixed tool is collected.
    """
    plain = MagicMock()
    plain.name = "read_file"
    assert sensitive_mcp_tool_names([github_tool, plain]) == [github_tool.name]
    assert readonly_mcp_tool_names([github_tool, plain]) == []


# ---------------------------------------------------------------------------
# Prefix application
# ---------------------------------------------------------------------------


def test_apply_mcp_tool_prefixes_renames_and_preserves_original() -> None:
    """Renaming must keep the original name on ``tool.metadata``.

    :return: None
    :raises AssertionError: If the rename or metadata is wrong.
    """
    tools = apply_mcp_tool_prefixes([_ListFilesTool()], "codegraph")
    assert tools[0].name == prefix_tool_name("codegraph", "list_files")
    metadata = tools[0].metadata
    assert metadata is not None
    assert metadata["original_name"] == "list_files"
    assert metadata["mcp_server"] == "codegraph"


def test_apply_mcp_tool_prefixes_keeps_existing_original_name() -> None:
    """An existing ``original_name`` metadata entry must not be overwritten.

    :return: None
    :raises AssertionError: If the original name is overwritten.
    """
    tool = _ListFilesTool()
    tool.metadata = {"original_name": "custom"}
    tools = apply_mcp_tool_prefixes([tool], "codegraph")
    metadata = tools[0].metadata
    assert metadata is not None
    assert metadata["original_name"] == "custom"


# ---------------------------------------------------------------------------
# Environment expansion
# ---------------------------------------------------------------------------


def test_expand_env_vars_substitutes_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``${VAR}`` references must be replaced from the environment.

    :param monkeypatch: Pytest fixture for environment manipulation.
    :return: None
    :raises AssertionError: If the substitution is wrong.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    expanded = expand_env_vars({"token": "${GITHUB_TOKEN}", "n": 1, "ok": True})
    assert expanded == {"token": "secret-value", "n": 1, "ok": True}


def test_expand_env_vars_keeps_missing_variable() -> None:
    """Missing variables must be left as-is.

    :return: None
    :raises AssertionError: If a missing variable is replaced.
    """
    assert expand_env_vars("${DOES_NOT_EXIST_123}") == "${DOES_NOT_EXIST_123}"
