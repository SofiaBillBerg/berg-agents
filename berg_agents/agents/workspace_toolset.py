"""Workspace toolset for berg_agents chat agents.

Wraps the framework-free :class:`~berg_agents.core.tool_spec.ToolSpec`
instances from :func:`~berg_agents.agents.factory.create_tools` in a
single named pydantic-ai toolset, following the documented custom-toolset
pattern (subclass :class:`~pydantic_ai.toolsets.WrapperToolset`,
override the extension points you need, delegate the rest).

Why a toolset instead of loose ``tool_plain`` registrations:

- One stable ``id`` (``"workspace"``) identifying every instruction
  and tool the workspace contributes - addressable as
  ``toolset:workspace`` and safe for durable execution.
- One ``get_instructions`` block teaching explore-first usage, instead
  of repeating usage guidance per tool and in the system prompt.
- Dynamic membership: ``read_only`` / ``allow_shell`` constructor
  flags select the registered subset per deployment, and ``call_tool``
  is the single audit/logging switch for every invocation.
- The harness loop and ``POST /api/tool/execute`` keep using the raw
  :class:`ToolSpec` list - this toolset is the pydantic-ai view of
  the same single source, not a second one.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from pydantic_ai.toolsets.wrapper import WrapperToolset

logger = logging.getLogger(__name__)

#: Stable toolset id. Instruction parts from
#: :meth:`WorkspaceToolset.get_instructions` are addressable as
#: ``toolset:workspace``; keep it constant - durable execution and
#: log readers key off this string, never the wording.
WORKSPACE_TOOLSET_ID = "workspace"

#: Usage guide injected into the agent's instructions once per run.
#: Complements (not replaces) the system prompt's authoritative tool
#: list: this text teaches *how* to work the filesystem, the prompt
#: names *what* exists.
_WORKSPACE_INSTRUCTIONS = """\
Workspace tools (toolset `workspace`) - how to work the filesystem:

- EXPLORE FIRST: call list_files before reading anything. Never guess
  at paths; use the exact paths list_files returns.
- Directories are not files: read_file on a directory tells you so -
  follow its guidance instead of retrying.
- SEARCH before assuming: use search_code to find definitions,
  references, or error strings instead of reading trees by hand.
- RUN things with bash (tests, builds, inspection). It has a timeout
  and truncated output; long jobs should be split or backgrounded by
  the caller. There is no other shell tool.
- WRITE with intent: write_file creates, edit_file replaces. Both
  need human approval in chat - the user sees an approve/reject
  dialog, so say what you are about to do before calling.
- COMPLEX work (multi-step plans, refactors, research) belongs in
  run_task, which drives the full harness pipeline for you.
- If a tool answers "not found" or "is a directory", follow the
  message. Do not retry the same call and do not invent tool names -
  the toolset above is the complete inventory.
"""


class WorkspaceToolset(WrapperToolset[None]):
    """File/shell workspace tools as one named, dynamic toolset.

    Builds an inner :class:`FunctionToolset` from
    :func:`~berg_agents.agents.factory.create_tools` (the same specs
    the harness loop and ``/api/tool/execute`` run) plus an optional
    ``run_task`` pipeline delegate, then adds identity, instructions,
    dynamic membership, and an audited call path on top.

    :param root_dir: Workspace root all file tools are bound to.
    :param harness: Optional harness for the ``run_task`` delegate.
        Omitted (e.g. read-only contexts) means no ``run_task`` tool.
    :param read_only: When True, only low-risk tools (list, read,
        search) are registered - the model cannot change files even
        if it tries. Mutating tools are withheld, not merely
        instructed away.
    :param allow_shell: When False, the ``bash`` tool is withheld
        (safe default for untrusted deployments).
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        harness: Any | None = None,
        read_only: bool = False,
        allow_shell: bool = True,
    ) -> None:
        """Initialize the workspace toolset.

        :param root_dir: Workspace root all file tools are bound to.
        :param harness: Optional harness for the ``run_task`` delegate.
            Omitted (e.g. read-only contexts) means no ``run_task`` tool.
        :param read_only: When True, only low-risk tools (list, read,
            search) are registered - the model cannot change files even
            if it tries. Mutating tools are withheld, not merely
            instructed away.
        :param allow_shell: When False, the ``bash`` tool is withheld
            (safe default for untrusted deployments).
        """
        from berg_agents.agents.factory import create_tools
        from pydantic_ai.toolsets import FunctionToolset

        inner: FunctionToolset[None] = FunctionToolset()
        for spec in create_tools(root_dir):
            if spec.execute is None:
                logger.warning(
                    "ToolSpec '%s' has no execute callable; skipping",
                    spec.name,
                )
                continue
            risk = spec.risk_class or "medium"
            if read_only and risk != "low":
                continue
            if not allow_shell and spec.name == "bash":
                continue
            inner.add_function(
                spec.execute,
                name=spec.name,
                description=spec.description or spec.name,
                requires_approval=risk != "low",
            )
        if harness is not None and not read_only:
            inner.add_function(
                self._make_run_task(harness),
                name="run_task",
                description=(
                    "Execute a complex task through the full BergAgents "
                    "harness pipeline (planning, subagents, file changes, "
                    "review). Use for multi-step work; reply directly for "
                    "simple questions."
                ),
                requires_approval=True,
            )
        super().__init__(wrapped=inner)
        self._root_dir = str(root_dir)

    @property
    def id(self) -> str | None:
        """Stable toolset id (``"workspace"``).

        :return: Toolset id.
        """
        return WORKSPACE_TOOLSET_ID

    async def get_instructions(self, ctx: Any) -> str:
        """Workspace usage guide, injected once per run.

        :param ctx: Context from the agent.
        :return: Usage instructions for the workspace toolset.
        """
        _ = ctx
        return _WORKSPACE_INSTRUCTIONS

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        """Audit-log every invocation, then delegate to the toolset.

        The single switch for all workspace tool execution: approval
        gating, retries, and result handling stay in the framework
        (via each tool's registration metadata); this layer owns
        observability.
        """
        logger.info("workspace tool call: %s(%s)", name, tool_args)
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            logger.warning("workspace tool %s failed: %s", name, exc)
            raise
        logger.debug(
            "workspace tool %s returned %d chars", name, len(str(result))
        )
        return result

    @staticmethod
    def _make_run_task(harness: Any) -> Any:
        """Build the ``run_task`` pipeline delegate bound to *harness*.

        :param harness: Harness to execute tasks through.
        :return: Async callable for the ``run_task`` tool.
        """

        async def _run_task(
            description: str, task_type: str = "generic"
        ) -> str:
            """Execute a complex task through the full BergAgents harness pipeline.

            Use this for tasks that need planning, subagents, file changes,
            HITL review, or multi-step execution - e.g. 'write a Python script',
            'refactor this module', or 'analyze the codebase'.

            For simple questions or conversation, reply directly without calling
            this tool.

            :param description: What the user wants done.
            :param task_type: Type of task (generic, code, research, etc.).
            :return: JSON-encoded result from the harness.
            """
            task: dict[str, Any] = {
                "description": description,
                "task_type": task_type,
                "metadata": {}}
            result = await asyncio.to_thread(
                harness.execute_task, task, task_id=f"chat-{id(description)}"
            )

            # If the harness needs human review, surface it so the caller
            # (VercelAIAdapter) emits the HITL event to the frontend.
            if (
                isinstance(result, dict)
                and result.get("status") == "needs_human_review"
            ):
                return json.dumps(
                    {
                        "status": "needs_human_review",
                        "review_reasons": result.get("review_reasons", []),
                        "risk_level": result.get("risk_level"),
                        "action_requests": result.get("action_requests", []),
                        "answer": result.get("implementation", {}).get(
                            "answer", ""
                        )}
                )

            if isinstance(result, str):
                return result
            if isinstance(result, list) and result:
                result = result[0] if isinstance(result[0], dict) else {}
            return (
                json.dumps(result) if isinstance(result, dict) else str(result)
            )

        return _run_task
