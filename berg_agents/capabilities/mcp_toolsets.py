"""MCP servers as pydantic-ai toolsets for chat agents.

Reads ``config/mcp.json`` in its native ``{"mcpServers": {...}}``
shape (Claude-style dict — *not* the list shape
:func:`~berg_agents.core.mcp.load_mcp_server_configs` expects, which
is why that file was previously configured but consumed by nothing):

- ``type: "remote"`` + ``url`` → streamed HTTP transport.
- ``type: "local"`` + ``command: [bin, ...args]`` → stdio transport.
- ``enabled: false`` → skipped. Missing flag means enabled.
- ``${VAR}`` / ``${env:VAR}`` placeholders expand from the environment.

Every toolset is renamed to ``mcp_<server>__<tool>`` to match the
documented tool contract the system prompt teaches, and tools from
sensitive servers (see :func:`~berg_agents.core.mcp.is_sensitive_server`)
are wrapped to require human approval — read-only servers stay
approval-free. Toolsets are cached process-wide and built
best-effort: a dead server logs a warning and is skipped, never
breaking chat.
"""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import json
import logging
import os
import re

from pathlib import Path
from typing import Any

from pydantic_ai.toolsets.wrapper import WrapperToolset


logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Expand ``${VAR}``/``${env:VAR}`` placeholders using the env."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _config_path() -> Path | None:
    """Locate ``config/mcp.json`` under the repo root."""
    root = Path(__file__).resolve().parent.parent.parent
    candidate = root / "config" / "mcp.json"
    return candidate if candidate.is_file() else None


def _load_config() -> dict[str, Any]:
    """Read the ``mcpServers`` mapping (empty dict on any problem)."""
    path = _config_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("MCP config unreadable (%s): %s", path, exc)
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


_CACHE: dict[str, Any] = {}
_LAST_NAMES: list[str] = []


class _ResilientToolset(WrapperToolset[None]):
    """Best-effort wrapper: a dead server yields no tools, never an error.

    MCP servers are external processes (stdio spawns, remote tunnels);
    any of them can fail between construction and use — cold-start
    races, revoked keys, dropped connections. Listing degrades to
    "no tools from this server" and calling degrades to a plain
    message, so one sick server cannot fail the chat turn. Approval
    handling, naming, retries, and lifecycle stay delegated.
    """

    async def get_tools(self, ctx: Any) -> dict[str, Any]:
        try:
            return await super().get_tools(ctx)
        except Exception as exc:
            logger.warning("MCP listing failed, hiding server: %s", exc)
            return {}

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any
    ) -> Any:
        try:
            return await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            logger.warning("MCP call %s failed: %s", name, exc)
            return f"Tool {name} is currently unavailable: {exc}"


def list_servers() -> list[dict[str, Any]]:
    """List configured MCP servers without spawning anything.

    Names plus enabled flags only - live tool names need a running
    session, so the slash palette and Context tab show servers from
    here and resolve tools at call time.

    :return: List of ``{"name", "enabled"}`` dicts.
    """
    return [
        {
            "name": name,
            "enabled": entry.get("enabled", True) is not False}
        for name, entry in _load_config().items()
        if isinstance(entry, dict)
    ]


def build_mcp_toolsets(*, refresh: bool = False) -> list[Any]:
    """Build one toolset per enabled MCP server (cached per process).

    Toolset objects are shared across requests; the stdio transports
    underneath default to keep-alive, so server subprocesses persist
    instead of respawning per chat message. Each agent run still opens
    its own session through the framework lifecycle, and the
    resilient wrapper degrades a dead server to "no tools" rather
    than failing the turn.

    :param refresh: Rebuild instead of reusing cached toolsets.
    :return: Toolsets ready for ``Agent(toolsets=[...])``.
    """
    from pydantic_ai.mcp import (
        MCPToolset,
        StdioTransport,
        StreamableHttpTransport,
    )

    from berg_agents.core.mcp import is_sensitive_server

    global _CACHE, _LAST_NAMES
    if _CACHE and not refresh:
        return list(_CACHE.values())

    toolsets: dict[str, Any] = {}
    for name, entry in _load_config().items():
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        try:
            server_type = str(entry.get("type", "")).strip().lower()
            if server_type == "remote" and entry.get("url"):
                headers = _expand(entry.get("headers") or None)
                client = StreamableHttpTransport(
                    url=str(entry["url"]),
                    headers=headers if isinstance(headers, dict) else None,
                )
            elif server_type == "local" and entry.get("command"):
                command = [_expand(c) for c in entry["command"]]
                command = [str(c) for c in command if str(c)]
                if not command:
                    raise ValueError("empty command")
                env = _expand(entry.get("environment") or entry.get("env"))
                # keep_alive is the fastmcp default (True); set it
                # explicitly so the subprocess survives between runs
                # instead of respawning per chat message.
                client = StdioTransport(
                    command=command[0],
                    args=command[1:],
                    env=env if isinstance(env, dict) else None,
                    keep_alive=True,
                )
            else:
                logger.warning(
                    "MCP server %r has no usable transport, skipping", name
                )
                continue
            toolset = MCPToolset(
                client, id=f"mcp-{name}", tool_error_behavior="failed"
            )
            if is_sensitive_server(name):
                toolset = toolset.approval_required()
            # PrefixedToolset joins as f"{prefix}_{tool}", so a single
            # trailing underscore yields the documented mcp_<srv>__<tool>.
            toolset = toolset.prefixed(f"mcp_{name}_")
            # A server that dies between build and run (cold stdio
            # races, revoked keys, dropped tunnels) must degrade to
            # "no tools from this server", never fail the whole turn.
            toolset = _ResilientToolset(toolset)
            toolsets[name] = toolset
            logger.info("MCP toolset ready: %s", name)
        except Exception as exc:
            logger.warning("MCP server %r unavailable, skipping: %s", name, exc)
    _CACHE = toolsets
    _LAST_NAMES = sorted(toolsets)
    return list(toolsets.values())


def mcp_toolset_names() -> list[str]:
    """Names from the most recent build (for diagnostics)."""
    return list(_LAST_NAMES)


__all__ = ["build_mcp_toolsets", "mcp_toolset_names"]
