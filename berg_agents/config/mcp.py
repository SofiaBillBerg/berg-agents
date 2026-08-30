"""MCP tool privilege scoping and configuration hardening.

This module is the single source of truth for how external MCP server tools
are named, classified, and (de)privileged inside the agent.

Why tool-name prefixing?
-------------------------
LangChain's :class:`~langchain.agents.middleware.HumanInTheLoopMiddleware`
matches tool calls by their **exact** name (see its ``after_model`` method).
Prompt instructions alone cannot reliably prevent a tool from being called,
and a prompt-injected instruction coming back through a tool result (e.g. a
GitHub issue body or a code-search hit) could otherwise drive a write-capable
MCP server such as GitHub. To make the privilege boundary enforceable we give
every MCP tool a deterministic, server-scoped name:

    ``mcp_<server>__<original_tool_name>``

Because the name is stable we can (a) gate whole servers behind Human-in-
the-Loop approval and (b) tell the model exactly which names exist, so it
never has to guess.

Servers are split into two classes:

* *Sensitive* servers (``SENSITIVE_SERVERS``) can change external state or
  local persisted memory -- every tool they expose is paused for explicit
  human approval before execution.
* *Read-only* servers (``READONLY_SERVERS``) are safe to call autonomously.

Callers use :func:`is_sensitive_server` / :func:`is_readonly_server` to
classify a server and :func:`sensitive_mcp_tool_names` /
:func:`readonly_mcp_tool_names` to collect the agent-facing names of the
tools that must (or must not) be gated.
"""

from __future__ import annotations

import os
import re
from typing import Any

from langchain.tools import BaseTool

# ---------------------------------------------------------------------------
# Naming convention
# ---------------------------------------------------------------------------

#: Prefix namespace for every MCP-sourced tool so names never collide with the
#: built-in ``edit-file`` / ``new-file`` / ... tools and are trivially
#: identifiable as external.
MCP_TOOL_PREFIX = "mcp"

#: Separator between the server name and the original tool name.
SERVER_SEP = "__"


def prefix_tool_name(server_name: str, tool_name: str) -> str:
    """Return the agent-facing name for an MCP tool.

    :param server_name: MCP server key (e.g. ``"github"``).
    :param tool_name: Original tool name advertised by the server.
    :return: ``"mcp_<server>__<tool>"``.
    """
    return f"{MCP_TOOL_PREFIX}_{server_name}{SERVER_SEP}{tool_name}"


# Matches ``mcp_<server>__<tool>`` and captures the server segment.
_PREFIX_RE = re.compile(
    rf"^{re.escape(MCP_TOOL_PREFIX)}_(?P<server>[^_]+){re.escape(SERVER_SEP)}.*$"
)


def server_from_prefixed(tool_name: str) -> str | None:
    """Extract the originating server name from a prefixed tool name.

    :param tool_name: A tool name, possibly prefixed.
    :return: The server name, or ``None`` when the name is not MCP-prefixed.
    """
    match = _PREFIX_RE.match(tool_name)
    return match.group("server") if match else None


# ---------------------------------------------------------------------------
# Server classification
# ---------------------------------------------------------------------------

#: Servers whose tools can mutate external state or persisted memory. Every
#: tool from one of these servers is interrupted for explicit human approval.
SENSITIVE_SERVERS: frozenset[str] = frozenset({"github", "memory"})

#: Servers that are strictly read-only and safe to call autonomously.
READONLY_SERVERS: frozenset[str] = frozenset({
    "codegraph",
    "context7",
    "docs-langchain",
    "reference-langchain",
})


def is_sensitive_server(server_name: str) -> bool:
    """Return ``True`` if *server_name* is a sensitive (approval-required) server.

    :param server_name: MCP server key.
    :return: Whether every tool from this server must be approved by a human.
    """
    return server_name in SENSITIVE_SERVERS


def is_readonly_server(server_name: str) -> bool:
    """Return ``True`` if *server_name* is a read-only (autonomous) server.

    :param server_name: MCP server key.
    :return: Whether every tool from this server is safe to call autonomously.
    """
    return server_name in READONLY_SERVERS


def apply_mcp_tool_prefixes(
    tools: list[BaseTool], server_name: str
) -> list[BaseTool]:
    """Rename MCP *tools* so each carries its originating server in its name.

    The original tool name is preserved on ``tool.metadata`` (``original_name``)
    for debugging; the underlying invocation is unchanged because the adapter
    binds the server call to the tool object, not to its display name.

    :param tools: Tools loaded from one MCP server.
    :param server_name: The server those tools came from.
    :return: The same tools, renamed in place and returned.
    """
    for tool in tools:
        original_name = tool.name
        new_name = prefix_tool_name(server_name, original_name)
        try:
            tool.name = new_name
        except (AttributeError, ValueError):
            # Extremely defensive: some tool wrappers forbid attribute
            # assignment. The rename is best-effort; if it fails the tool
            # still works, it just keeps its un-prefixed name.
            continue
        metadata = getattr(tool, "metadata", None)
        if isinstance(metadata, dict):
            # Capture the *original* name before it was prefixed.
            metadata.setdefault("original_name", original_name)
            metadata["mcp_server"] = server_name
    return tools


def sensitive_mcp_tool_names(tools: list[BaseTool]) -> list[str]:
    """Return the names of MCP tools that must be gated behind human approval.

    :param tools: The full tool list available to the agent.
    :return: Names of tools whose server is in :data:`SENSITIVE_SERVERS`.
    """
    names: list[str] = []
    for tool in tools:
        server = server_from_prefixed(tool.name)
        if server is not None and is_sensitive_server(server):
            names.append(tool.name)
    return names


def readonly_mcp_tool_names(tools: list[BaseTool]) -> list[str]:
    """Return the names of MCP tools that are safe to call autonomously.

    :param tools: The full tool list available to the agent.
    :return: Names of tools whose server is in :data:`READONLY_SERVERS`.
    """
    names: list[str] = []
    for tool in tools:
        server = server_from_prefixed(tool.name)
        if server is not None and is_readonly_server(server):
            names.append(tool.name)
    return names


# ---------------------------------------------------------------------------
# Secret handling: expand ``${VAR}`` references from the environment
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


def _expand_value(value: str) -> str:
    """Replace ``${VAR}`` substrings in *value* using :data:`os.environ`."""
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def expand_env_vars(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` references inside a config structure.

    Strings are expanded against the current environment; other types
    (bools, ints, nested dicts/lists) are returned unchanged. Used so that
    secrets can live in a git-ignored ``.env`` file and be referenced from
    ``.mcp.json`` as ``"${GITHUB_PERSONAL_ACCESS_TOKEN}"`` instead of being
    committed in plaintext.

    :param obj: A dict/list/str/primitive from an MCP server config.
    :return: The same structure with string values expanded.
    """
    if isinstance(obj, str):
        return _expand_value(obj)
    if isinstance(obj, dict):
        return {key: expand_env_vars(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(item) for item in obj]
    return obj
