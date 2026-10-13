"""Pydantic AI adapter for BergAgents tools and agent construction.

Builds a :class:`~pydantic_ai.Agent` whose tools come from a single
:class:`~berg_agents.agents.workspace_toolset.WorkspaceToolset` — file
tools plus staged plan/implement subagent delegates. Used by the
``VercelAIAdapter`` streaming endpoint.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _shell_allowed() -> bool:
    """Whether the ``bash`` tool may be offered to the model.

    Kill-switch for untrusted deployments: set
    ``BERG_AGENT_ALLOW_SHELL=0`` (or false/no/off) to withhold the
    shell tool entirely. Defaults to allowed.

    :return: True if the shell tool is allowed, False if withheld.
    """
    return os.getenv("BERG_AGENT_ALLOW_SHELL", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off"}


def build_chat_agent(
        model_id: str | None = None,
        *,
        root_dir: str = ".",
        plugin_tools: list[Any] | None = None,
        disabled_mcp: frozenset[str] = frozenset(),
        disabled_skills: frozenset[str] = frozenset(),
) -> Any:
    """Build a pydantic_ai ``Agent`` for the streaming chat endpoint.

    The agent receives a single
    :class:`~berg_agents.agents.workspace_toolset.WorkspaceToolset`
    (id ``"workspace"``): file/shell tools plus staged ``plan_task``
    / ``implement_task`` subagent delegates, with per-tool approval
    flags and a usage guide carried by the toolset itself. Enabled
    plugin tools (e.g. shared-todo) are attached as plain tools.

    System prompt, model, and temperature all come from configuration
    (``.berg_config/bergagents.jsonc`` and ``.berg_config/profiles.yaml``) - never
    hardcoded.

    :param model_id: Model identifier to resolve; falls back to the session's
        or settings' default.
    :param root_dir: Workspace root for file tools.
    :param plugin_tools: Extra pydantic-ai tools from enabled plugins;
        pass ``None`` (or omit) for a plugin-free agent.
    :param disabled_mcp: MCP server keys to withhold (disabled toggles).
    :param disabled_skills: Chat skill ids (``skill-<name>``) to withhold.
    :return: A configured ``Agent`` ready for ``VercelAIAdapter``.
    """
    from berg_agents.agents.workspace_toolset import WorkspaceToolset
    from berg_agents.capabilities.mcp_toolsets import build_mcp_toolsets
    from berg_agents.capabilities.skills import load_skill_capabilities
    from berg_agents.capabilities.web_backends import (
        make_web_fetch,
        make_web_search,
    )
    from berg_agents.config.settings import get_settings
    from berg_agents.providers.models import resolve_model_instance
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import WebFetch, WebSearch
    from pydantic_ai_harness import Planning

    # Resolve the model from .berg_config - resolve_model_instance reads
    # bergagents.jsonc and returns a fully-configured OpenAIChatModel.
    model = resolve_model_instance(model_id or "")

    # Build the system prompt from settings (.berg_config-driven, not hardcoded).
    settings = get_settings()
    system_prompt = (
        settings.system_prompt.format(root_dir=root_dir)
        if f"{root_dir}" in settings.system_prompt
        else settings.system_prompt
    )

    # Shared workspace root for file tools and subagent delegates.
    toolset = WorkspaceToolset(
        root_dir,
        allow_shell=_shell_allowed(),
    )

    agent = Agent(
        model,
        system_prompt=system_prompt,
        tool_timeout=30,
        # Two output retries so one malformed tool call gets a
        # recovery chance instead of failing the whole turn.
        # NOTE: no approval-handling capability here on purpose.
        # Tools flagged requires_approval (bash, edit_file,
        # write_file, implement_task) pause the run as
        # DeferredToolRequests; the chat endpoint declares that
        # output type so the VercelAIAdapter streams an approval
        # request, and the frontend answers it with an approval
        # response. Every approval is collected through the UI.
        retries={"output": 3},
        # NOTE: Enabled plugin tools (shared-todo pilot). Empty by
        # default — low-risk tools need no HITL approval.
        tools=list(plugin_tools) if plugin_tools else [],
        toolsets=[toolset, *build_mcp_toolsets(exclude=disabled_mcp)],
        capabilities=[
            # Provider-adaptive web tools: provider-native first where
            # the model supports it, local implementation otherwise.
            # The local side tries the configured web backends in
            # order (settings.web_search_backends, default
            # ollama → duckduckgo → direct).
            WebSearch(local=make_web_search(settings.web_search_backends)),
            WebFetch(local=make_web_fetch(settings.web_search_backends)),
            # Model-owned task plans with a live reminder: multi-step
            # work shows its todos/plan in the transcript instead of
            # happening invisibly. Eager — planning is core behavior.
            Planning(),
            # Repo skills (SKILL.md manuals) as deferred capabilities:
            # one-line catalog entries until the model loads one.
            # Point BERG_AGENT_SKILLS at e.g. ".agents/skills".
            # Disabled skill plugins are withheld here so the toggle
            # is honest end to end.
            *[
                cap
                for cap in load_skill_capabilities(
                    settings.skills, root_dir=root_dir
                )
                if getattr(cap, "id", "") not in disabled_skills
            ]],
    )

    return agent
