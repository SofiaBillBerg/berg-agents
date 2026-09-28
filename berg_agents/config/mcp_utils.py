"""MCP tool privilege scoping and configuration hardening.

This module is the single source of truth for how external MCP server tools
are named, classified, and (de)privileged inside the agent.

Why tool-name prefixing?
-------------------------
To make the privilege boundary enforceable we give every MCP tool a
deterministic, server-scoped name:

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
:function:`readonly_mcp_tool_names` to collect the agent-facing names of the
tools that must (or must not) be gated.
"""

from __future__ import annotations

import os
import re
from typing import Any

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
READONLY_SERVERS: frozenset[str] = frozenset(
    {
        "codegraph",
        "context7",
    }
)


def is_sensitive_server(
    server_name: str, enabled_servers: frozenset[str] | None = None
) -> bool:
    """Return ``True`` if *server_name* is a sensitive (approval-required) server.

    When *enabled_servers* is provided (from loaded MCP server config),
    a server not in the enabled set is treated as not sensitive.

    :param server_name: MCP server key.
    :param enabled_servers: Optional set of server names that are configured
        and enabled. When provided, classification respects config.
    :return: Whether every tool from this server must be approved by a human.
    """
    if enabled_servers is not None and server_name not in enabled_servers:
        return False
    return server_name in SENSITIVE_SERVERS


def is_readonly_server(
    server_name: str, enabled_servers: frozenset[str] | None = None
) -> bool:
    """Return ``True`` if *server_name* is a read-only (autonomous) server.

    When *enabled_servers* is provided (from loaded MCP server config),
    a server not in the enabled set is treated as not read-only.

    :param server_name: MCP server key.
    :param enabled_servers: Optional set of server names that are configured
        and enabled. When provided, classification respects config.
    :return: Whether every tool from this server is safe to call autonomously.
    """
    if enabled_servers is not None and server_name not in enabled_servers:
        return False
    return server_name in READONLY_SERVERS


# ---------------------------------------------------------------------------
# Tool-name collection (gating)
# ---------------------------------------------------------------------------


def sensitive_mcp_tool_names(
    tools: list[Any],
    enabled_servers: frozenset[str] | None = None,
) -> list[str]:
    """Collect the agent-facing names of tools that require human approval.

    Only tools whose prefixed name resolves to a sensitive server are
    collected; unprefixed tools (built-ins) are never MCP-gated.

    :param tools: Tool objects exposing a ``name`` attribute.
    :param enabled_servers: Optional set of server names from loaded config.
        When provided, sensitive/read-only classification respects config.
    :return: Names of tools from sensitive servers, in input order.
    """
    names: list[str] = []
    for tool in tools:
        server = server_from_prefixed(tool.name)
        if server is not None and is_sensitive_server(server, enabled_servers):
            names.append(tool.name)
    return names


def readonly_mcp_tool_names(
    tools: list[Any],
    enabled_servers: frozenset[str] | None = None,
) -> list[str]:
    """Collect the agent-facing names of tools that are safe to call.

    Only tools whose prefixed name resolves to a read-only server are
    collected; unprefixed tools (built-ins) are skipped.

    :param tools: Tool objects exposing a ``name`` attribute.
    :param enabled_servers: Optional set of server names from loaded config.
        When provided, sensitive/read-only classification respects config.
    :return: Names of tools from read-only servers, in input order.
    """
    names: list[str] = []
    for tool in tools:
        server = server_from_prefixed(tool.name)
        if server is not None and is_readonly_server(server, enabled_servers):
            names.append(tool.name)
    return names


def apply_mcp_tool_prefixes(tools: list[Any], server_name: str) -> list[Any]:
    """Rename *tools* in place to their server-scoped agent-facing names.

    The original name is preserved on ``tool.metadata`` (under
    ``"original_name"``, alongside ``"mcp_server"``) so the MCP client
    can translate back when dispatching. An existing ``original_name``
    entry is never overwritten, so double-prefixing stays reversible.

    :param tools: Tool objects with writable ``name``/``metadata``.
    :param server_name: MCP server key the tools were loaded from.
    :return: The same list, renamed in place.
    """
    for tool in tools:
        original = tool.name
        metadata = getattr(tool, "metadata", None) or {}
        metadata.setdefault("original_name", original)
        metadata.setdefault("mcp_server", server_name)
        tool.metadata = metadata
        tool.name = prefix_tool_name(server_name, original)
    return tools


# ---------------------------------------------------------------------------
# Secret handling: expand ``${VAR}`` / ``${env:VAR}`` references from the environment
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)}")


def _expand_value(value: str) -> str:
    """Replace ``${VAR}`` / ``${env:VAR}`` substrings in *value* using :data:`os.environ`."""
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def expand_env_vars(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` / ``${env:VAR}`` references inside a config structure.

    Strings are expanded against the current environment; other types
    (bools, ints, nested dicts/lists) are returned unchanged. Used so that
    secrets can live in a git-ignored ``.env`` file and be referenced from
    ``mcp.json`` as ``"${GITHUB_PERSONAL_ACCESS_TOKEN}"`` instead of being
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
