# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Tool endpoints.

Extracted from ``create_router`` — one concern per module. Covers the
tool catalog (workspace file tools + harness entry points) and the
synchronous tool-execution endpoint the webapp's slash commands use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.schemas import ToolExecuteRequest, ToolExecuteResponse
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


async def _run_task_tool(
    harness: Harness, args: dict[str, Any]
) -> ToolExecuteResponse:
    """Run one task through the harness and return its tool response.

    Isolated helper so ``register_tool_routes`` stays under the complexity
    threshold. A gated (mutating) task returns the plan for approval
    instead of executing; approval happens in the chat approval flow,
    not through a re-invoke on this endpoint.

    :param harness: Shared harness.
    :param args: Tool arguments.
    :return: Tool response with the JSON-encoded result.
    """
    task: dict[str, Any] = {
        "description": str(args.get("description", "")),
        "task_type": str(args.get("task_type", "generic")),
        "metadata": {}}
    if not task["description"]:
        return ToolExecuteResponse(
            tool="run_task",
            output="Missing 'description': tell me what to do, "
            'e.g. /run_task {"description": "summarize README"}.',
            status="error",
        )
    result = await asyncio.to_thread(
        harness.execute_task, task, task_id=f"tool-{id(task)}"
    )
    if isinstance(result, str):
        output = result
    else:
        import json as _json

        try:
            output = _json.dumps(result, indent=2, default=str)
        except (TypeError, ValueError):
            output = str(result)
    return ToolExecuteResponse(tool="run_task", output=output)


#: The MCP surfaces an agent may use DIRECTLY, without a specialist run.
#
# Sofia's decision (2026-11-16): an advisor that can only read the files is half
# an advisor, so the orchestrator can also look things up — documentation, code
# intelligence, her memory — without delegating. Two ways an MCP server can be
# listed here:
#
# - **autonomous** — every tool from this server may be called directly. That is
#   berg's existing `READONLY_SERVERS` policy (`codegraph`, `context7`), which is
#   already the "safe to run without asking" set, plus the two knowledge stores
#   Sofia chose to open fully (`memory`, `mempalace-light`) — writing to her own
#   memory is not a workspace write, and the file gate was never protecting it.
# - **reads** — only the named tools may be called. Used for `github`, where
#   Sofia chose reads-only: searching an issue is a lookup, opening one is not.
#
# MCP schemas do not declare which of their tools mutate, so an explicit list is
# the only honest mechanism — `READONLY_SERVERS` says as much about a whole
# server, and here it is said tool by tool.
AUTONOMOUS_MCP_SERVERS: frozenset[str] = frozenset({
    "codegraph",
    "context7",
    "memory",
    "mempalace-light"})

#: GitHub's read-only tools, named explicitly (the server cannot say which of
#: its tools mutate).
GITHUB_READ_TOOLS: frozenset[str] = frozenset({
    "get_issue",
    "get_pull_request",
    "get_pull_request_diff",
    "get_pull_request_files",
    "list_issues",
    "list_pull_requests",
    "list_commits",
    "search_code",
    "search_issues",
    "search_users"})


#: How far to unwrap berg's toolset wrappers looking for the MCP client. Two is
#: what today's stacking needs (prefixed → resilient → MCP toolset); the bound
#: is there so a future wrapper cannot make this walk forever.
_MAX_TOOLSET_UNWRAP = 5


def _tool_schema(tool: Any) -> dict[str, Any]:
    """One MCP tool's argument schema, in berg's own JSON-Schema dialect.

    Uses berg's existing conversion (`_params_from_schema`, `ToolSpec.to_openai_tool`)
    rather than a second hand-written passthrough: the dialect the whole webapp
    already speaks, and the MCP → ToolParam translation that already existed.

    :param tool: A tool object as the MCP client lists one.
    :return: ``parameters`` in berg's schema shape, empty when the tool
        advertises none.
    """
    from collections.abc import Mapping

    from berg_agents.tools.mcp import _params_from_schema
    from berg_agents.tools.tool_spec import ToolSpec

    # `input_schema` is the MCP SDK v2 name; `inputSchema` is the deprecated
    # alias, so both are read.
    raw = getattr(tool, "input_schema", None)
    if raw is None:
        raw = getattr(tool, "inputSchema", None)
    if not isinstance(raw, Mapping):
        return {}
    spec = ToolSpec(
        name=str(getattr(tool, "name", "")),
        description=str(getattr(tool, "description", "") or ""),
        params=_params_from_schema(raw),
    )
    return spec.to_openai_tool()["function"]["parameters"]


def _mcp_client(toolset: Any) -> Any:
    """The MCP client behind berg's wrapped toolset.

    ``_ResilientToolset`` wraps the real toolset (a ``WrapperToolset``), so
    ``client`` — the MCP server, with ``list_tools``/``call_tool`` — is one
    ``wrapped`` away. Reaching it is what lets a route ask a server directly,
    without a run context.

    :param toolset: A toolset as :func:`named_mcp_toolsets` returns one.
    :return: The MCP client, or None when it cannot be reached.
    """
    seen = 0
    candidate = toolset
    while candidate is not None and seen < _MAX_TOOLSET_UNWRAP:
        client = getattr(candidate, "client", None)
        if client is not None:
            return client
        candidate = getattr(candidate, "wrapped", None)
        seen += 1
    return None


def _allowed_mcp_call(server: str, tool: str) -> bool:
    """Whether *server*'s *tool* may be called directly, outside an agent run.

    Deliberately a deny-by-default: an unnamed server or tool is not allowed,
    because the alternative is that a new MCP server appears in the config and
    becomes callable by an agent that never asks.

    :param server: The MCP server key.
    :param tool: The tool name as the server advertises it.
    :return: Whether the call is permitted here.
    """
    if server in AUTONOMOUS_MCP_SERVERS:
        return True
    if server == "github":
        return tool in GITHUB_READ_TOOLS
    return False


async def _list_mcp_tools() -> dict[str, Any]:
    """List the MCP tools an agent may call directly, with their schemas.

    Built from the live toolsets (cached process-wide, best-effort: a dead
    server is skipped rather than failing the list), because tool names and
    arguments are the SERVER's to define — hard-coding them here would mean a
    list that silently drifts from the servers it describes.

    Only servers on the direct-call allowlist are listed, so what a caller sees
    is what it may actually call.

    :return: ``{tools: [...]}``, one entry per allowed tool.
    """
    from berg_agents.tools.mcp_toolsets import named_mcp_toolsets

    tools: list[dict[str, Any]] = []
    for server, toolset in named_mcp_toolsets():
        client = _mcp_client(toolset)
        if client is None:
            continue
        try:
            # The toolset's `client` is the MCP server itself. Asking the
            # toolset (`get_tools(ctx)`) would need a live run context that only
            # an agent turn has; asking the client needs nothing, which is what
            # a direct route is for.
            async with client as entered:
                specs = await entered.list_tools()
                rows = [
                    (
                        str(getattr(t, "name", "")),
                        str(getattr(t, "description", "") or ""),
                        # The argument SCHEMAS, not just the name. A model cannot
                        # infer nested argument names from a one-line
                        # description, so a generic "call any tool" surface
                        # without these is a trap: it will guess, fail, and
                        # burn its step budget retrying.
                        #
                        # `input_schema` is the MCP SDK v2 name; `inputSchema`
                        # is the deprecated alias, so both are read.
                        _tool_schema(t),
                    )
                    for t in specs
                ]
        except Exception as exc:  # A dead server must not break the list.
            logger.warning("MCP listing skipped for %s: %s", server, exc)
            continue
        for bare, description, schema in rows:
            if not _allowed_mcp_call(server, bare):
                continue
            tools.append({
                "server": server,
                "tool": bare,
                "description": description,
                "parameters": schema})
    return {"tools": tools}


async def _execute_mcp_tool(
    server: str, tool: str, request: Request
) -> dict[str, Any]:
    """Run one MCP tool directly and return its output.

    The route that makes an MCP server reachable outside an agent run — the
    point being that the orchestrator can look things up (documentation, code,
    her own memory) without starting a specialist for a read. The allowlist is
    enforced HERE, in berg, rather than trusted from the caller: what may run
    unattended is berg's decision, not the client's.

    :param server: The MCP server key.
    :param tool: The tool name as the server advertises it.
    :param request: JSON body with ``args`` (the tool's arguments).
    :return: The tool's output as text, and the server/tool that ran it.
    :raises HTTPException: 403 when that server's tool is not on the
        direct-call allowlist, 404 for an unknown server or tool.
    """
    from berg_agents.tools.mcp_toolsets import named_mcp_toolsets

    if not _allowed_mcp_call(server, tool):
        raise HTTPException(
            status_code=403,
            detail=(
                f"{server}.{tool} is not on the direct-call allowlist. "
                "Reads that answer the question are; anything that changes "
                "something belongs in a specialist, behind a gate."
            ),
        )

    body = await request.json()
    args = body.get("args") if isinstance(body, dict) else {}
    if not isinstance(args, dict):
        args = {}

    for name, toolset in named_mcp_toolsets():
        if name != server:
            continue
        client = _mcp_client(toolset)
        if client is None:
            continue
        try:
            # Ask the MCP server itself, not the toolset: `call_tool` on the
            # toolset needs a run context, and the client's does not.
            async with client as entered:
                specs = await entered.list_tools()
                known = {str(getattr(t, "name", "")) for t in specs}
                if tool not in known:
                    raise HTTPException(
                        status_code=404,
                        detail=f"{server} has no tool named {tool!r}",
                    )
                result = await client.call_tool(tool, args)
                text = (
                    result
                    if isinstance(result, str)
                    else json.dumps(result, default=str)
                )
                return {"server": server, "tool": tool, "output": text}
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("MCP call %s.%s failed: %s", server, tool, exc)
            raise HTTPException(
                status_code=502, detail=f"{server}.{tool} unavailable: {exc}"
            ) from exc

    raise HTTPException(
        status_code=404, detail=f"No MCP server named {server!r}"
    )


def register_tool_routes(
    router: APIRouter, *, harness: Harness, sessions: SessionManager
) -> None:
    """Register the tool catalog and synchronous execution endpoints.

    :param router: Router to attach endpoints to.
    :param harness: Shared harness (needed for ``run_task``).
    :param sessions: Session store (root dir for workspace file tools).
    """

    @router.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        """List tools the ``/api/tool/execute`` endpoint can run.

        Workspace file tools (name + one-line description) plus the
        harness entry points. ``plan_task`` / ``implement_task`` are
        marked ``delegated``: they run inside the chat turn as chat
        tools, so the web UI routes ``/plan`` / ``/implement`` as chat
        messages instead of executing them directly. MCP *servers* are
        listed separately - their live tool names need a running session.

        :return: Dict with ``tools`` and ``mcp_servers`` lists.
        """
        from berg_agents.agents.factory import create_tools
        from berg_agents.tools.mcp_toolsets import list_servers

        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "source": "workspace"}
            for spec in create_tools(root_dir=sessions._harness_root_dir())
            if spec.execute is not None
        ]
        tools.extend([
            {
                "name": "run_task",
                "description": (
                    "Run the full harness pipeline on a description."
                ),
                "source": "harness"},
            {
                "name": "plan_task",
                "description": (
                    "Decompose a task into an ordered step plan. "
                    "Runs inside a chat turn."
                ),
                "source": "delegate"},
            {
                "name": "implement_task",
                "description": (
                    "Execute an approved step plan. Runs inside a chat turn."
                ),
                "source": "delegate"}])
        return {"tools": tools, "mcp_servers": list_servers()}

    @router.get("/api/mcp/tools")
    async def list_mcp_tools() -> dict[str, Any]:
        """The MCP tools an agent may call directly, with their schemas.

        :return: ``{tools: [...]}``, one entry per allowed tool.
        """
        return await _list_mcp_tools()

    @router.post("/api/mcp/{server}/tools/{tool}")
    async def execute_mcp_tool(
        server: str, tool: str, request: Request
    ) -> dict[str, Any]:
        """Run one MCP tool directly and return its output.

        :param server: The MCP server key.
        :param tool: The tool name as the server advertises it.
        :param request: JSON body with ``args``.
        :return: The tool's output, and the server/tool that ran it.
        """
        return await _execute_mcp_tool(server, tool, request)

    @router.post("/api/tool/execute")
    async def execute_tool(request: ToolExecuteRequest) -> ToolExecuteResponse:
        """Execute one tool synchronously and return its output.

        Switches on the tool name and runs the matching
        :class:`~berg_agents.tools.tool_spec.ToolSpec` (file tools)
        or the full harness pipeline (``run_task``). This is the
        endpoint the webapp's ``executeTool`` (slash commands like
        ``/read_file``) calls. Tool functions already return
        human-readable messages instead of raising, so failures
        arrive as ``status="error"`` output - never tracebacks.

        :param request: Tool name plus arguments (mapping, or a bare
            string treated as ``file_path``).
        :return: Tool name, string output, and status.
        :raises HTTPException: 404 for unknown tool names.
        """
        from berg_agents.agents.factory import create_tools

        name = (request.tool or "").strip()
        args = request.args
        if isinstance(args, str):
            args = {"file_path": args} if args else {}
        if not isinstance(args, dict):
            args = {}

        if name == "run_task":
            return await _run_task_tool(harness, args)

        specs = {
            spec.name: spec
            for spec in create_tools(root_dir=sessions._harness_root_dir())
        }
        spec = specs.get(name)
        if spec is None or spec.execute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tool '{name}'. "
                f"Available: {', '.join(sorted(specs))}, run_task.",
            )
        try:
            result = spec.execute(**args)
            if asyncio.iscoroutine(result):
                result = await result
            output = result if isinstance(result, str) else str(result)
            return ToolExecuteResponse(tool=name, output=output)
        except TypeError as exc:
            # Wrong kwargs (e.g. missing content for write_file).
            return ToolExecuteResponse(
                tool=name,
                output=f"Bad arguments for {name}: {exc}. "
                f'Send {{"file_path": ..., "content": ...}} where needed.',
                status="error",
            )
        except Exception as exc:  # Defensive: never leak tracebacks.
            logger.warning("Tool %s failed: %s", name, exc, exc_info=True)
            return ToolExecuteResponse(
                tool=name, output=f"{name} failed: {exc}", status="error"
            )
