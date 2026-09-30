"""Pydantic AI adapter for BergAgents tools and agent construction.

Converts :class:`~berg_agents.core.tool_spec.ToolSpec` instances into
pydantic_ai tool callables and builds a :class:`~pydantic_ai.Agent`
configured from the app settings.

This bridges the framework-free ``ToolSpec`` (which the harness uses for
the deterministic planning loop) to pydantic_ai's tool model (used by the
``VercelAIAdapter`` streaming endpoint).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_chat_agent(
    model_id: str | None = None,
    *,
    root_dir: str = ".",
) -> Any:
    """Build a pydantic_ai ``Agent`` for the streaming chat endpoint.

    The agent receives:
    - File-operation tools (list_files, read_file, search_code, bash,
      edit_file, write_file) registered from
      :func:`~berg_agents.agents.factory.create_tools` via ``tool_plain``.
    - A ``run_task`` tool that delegates to the full BergAgents harness when
      the model decides complex work is needed.

    System prompt, model, and temperature all come from configuration
    (``config/bergagents.jsonc`` and ``config/profiles.yaml``) - never
    hardcoded.

    :param model_id: Model identifier to resolve; falls back to the session's
        or settings' default.
    :param root_dir: Workspace root for file tools.
    :return: A configured ``Agent`` ready for ``VercelAIAdapter``.
    """
    from berg_agents.agents.factory import create_tools
    from berg_agents.config.settings import get_settings
    from berg_agents.core.harness import Harness
    from berg_agents.providers.models import resolve_model_instance
    from pydantic_ai import Agent

    # Resolve the model from config - resolve_model_instance reads
    # bergagents.jsonc and returns a fully-configured OpenAIChatModel.
    model = resolve_model_instance(model_id or "")
    tools = create_tools(root_dir=root_dir)

    # Build the system prompt from settings (config-driven, not hardcoded).
    settings = get_settings()
    system_prompt = (
        settings.system_prompt.format(root_dir=root_dir)
        if "{root_dir}" in settings.system_prompt
        else settings.system_prompt
    )

    agent = Agent(
        model,
        system_prompt=system_prompt,
        tool_timeout=30,
        # Two output retries so one malformed tool call gets a
        # recovery chance instead of failing the whole turn.
        # NOTE: no approval-handling capability here on purpose.
        # Tools flagged requires_approval (bash, edit_file,
        # write_file, run_task) pause the run as DeferredToolRequests;
        # the chat endpoint declares that output type so the
        # VercelAIAdapter streams an approval request, and the
        # frontend answers it with an approval response. Approving
        # happens in the UI — never silently.
        retries={"output": 3},
    )

    # Register file-operation tools via tool_plain.
    # tool_plain introspects the function signature to build the JSON schema.
    for spec in tools:
        if spec.execute is None:
            logger.warning(
                "ToolSpec '%s' has no execute callable; skipping", spec.name
            )
            continue

        agent.tool_plain(
            spec.execute,
            name=spec.name,
            description=spec.description or spec.name,
            requires_approval=(spec.risk_class or "medium") != "low",
        )

    # Shared harness for the run_task tool - delegates to the full pipeline
    # (planning, subagents, HITL, implementation).
    harness = Harness(enable_inference=True)

    async def _run_task(description: str, task_type: str = "generic") -> str:
        """Execute a complex task through the full BergAgents harness pipeline.

        Use this for tasks that need planning, subagents, file changes,
        HITL review, or multi-step execution - e.g. 'write a Python script',
        'refactor this module', or 'analyze the codebase'.

        For simple questions or conversation, reply directly without calling
        this tool.

        Args:
            description: What the user wants done.
            task_type: Type of task (generic, code, research, etc.).
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
        return json.dumps(result) if isinstance(result, dict) else str(result)

    agent.tool_plain(
        _run_task,
        name="run_task",
        description=_run_task.__doc__
        or "Execute a complex task through the full BergAgents pipeline.",
        requires_approval=True,
    )

    return agent
