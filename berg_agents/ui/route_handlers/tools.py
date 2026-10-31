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
import logging
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.schemas import ToolExecuteRequest, ToolExecuteResponse
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


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
        marked ``delegated``: they run inside the chat turn, so the
        web UI routes ``/plan`` / ``/implement`` through ``run_task``
        instead of executing them directly. MCP *servers* are listed
        separately - their live tool names need a running session.

        :return: Dict with ``tools`` and ``mcp_servers`` lists.
        """
        from berg_agents.agents.factory import create_tools
        from berg_agents.capabilities.mcp_toolsets import list_servers

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
                    "Runs in chat; the UI routes /plan through run_task."
                ),
                "source": "delegate"},
            {
                "name": "implement_task",
                "description": (
                    "Execute an approved step plan. Runs in chat; "
                    "the UI routes /implement through run_task."
                ),
                "source": "delegate"}])
        return {"tools": tools, "mcp_servers": list_servers()}

    @router.post("/api/tool/execute")
    async def execute_tool(request: ToolExecuteRequest) -> ToolExecuteResponse:
        """Execute one tool synchronously and return its output.

        Switches on the tool name and runs the matching
        :class:`~berg_agents.core.tool_spec.ToolSpec` (file tools)
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
            task: dict[str, Any] = {
                "description": str(args.get("description", "")),
                "task_type": str(args.get("task_type", "generic")),
                "metadata": {}}
            # NOTE: HITL resume fields. When the frontend approves/rejects/
            # edits a gated plan, it re-invokes run_task with these so the
            # orchestrator skips the gate (or records the rejection) instead
            # of re-planning. task_id pins the resumed run to the same id.
            if "task_id" in args:
                task["task_id"] = str(args.get("task_id"))
            metadata = task["metadata"]
            if "hitl_decision" in args:
                metadata["hitl_decision"] = str(args.get("hitl_decision"))
            if "edited_action" in args:
                metadata["edited_action"] = args.get("edited_action")
            if not task["description"]:
                return ToolExecuteResponse(
                    tool=name,
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
            return ToolExecuteResponse(tool=name, output=output)

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
