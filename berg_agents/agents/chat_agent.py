# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
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
    active_agent: str | None = None,
    active_agent_description: str | None = None,
) -> Any:
    """Build a pydantic_ai ``Agent`` for the streaming chat endpoint.

    The agent receives a single
    :class:`~berg_agents.agents.workspace_toolset.WorkspaceToolset`
    (id ``"workspace"``): file/shell tools plus staged ``plan_task``
    / ``implement_task`` subagent delegates, with per-tool approval
    flags and a usage guide carried by the toolset itself. Enabled
    plugin tools (e.g. shared-todo) are attached as plain tools.

    System prompt, model, and temperature all come from configuration
    (``.berg-agents/bergagents.jsonc`` and ``.berg-agents/profiles.yaml``) - never
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
    from berg_agents.core.shared_context import SECTIONS, SharedContext
    from berg_agents.plugin_system.context_capabilities import (
        build_context_capabilities,
    )
    from berg_agents.providers.models import resolve_model_instance
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import WebFetch, WebSearch
    from pydantic_ai_harness import Planning

    # Resolve the model from .berg-agents - resolve_model_instance reads
    # bergagents.jsonc and returns a fully-configured OpenAIChatModel.
    model = resolve_model_instance(model_id or "")

    # Build the system prompt from settings (config-driven, not hardcoded).
    settings = get_settings()
    system_prompt = (
        settings.system_prompt.format(root_dir=root_dir)
        if f"{root_dir}" in settings.system_prompt
        else settings.system_prompt
    )

    # Active agent routing: when the user has chosen an agent (via
    # /api/agents/active), this turn runs as that agent - its persona
    # and preferred complexity shape the prompt. Mirrors model selection.
    active_agent = (active_agent or "").strip() or None
    if active_agent:
        persona = f"You are acting as the '{active_agent}' agent."
        if active_agent_description:
            persona = f"{persona} {active_agent_description}"
        system_prompt = (
            f"{persona}\n\n{system_prompt}" if system_prompt else persona
        )

    # Shared Context: the human-owned foundation this agent leverages.
    # Rendered fresh per request (this builder runs per /api/chat/stream),
    # project scope shadowing global. The block below is the read path;
    # the two tools are the contribute path (author + why recorded).
    shared_context = SharedContext.resolve(root_dir)
    rendered_context = shared_context.render()
    if rendered_context:
        system_prompt += (
            "\n\n# Shared context (human-owned; project shadows global)\n"
            f"{rendered_context}\n\n"
            "This is your persistent shared context with the user, kept as plain "
            "files the human also edits. Keep it current: use "
            "write_shared_context / append_shared_context to record durable "
            "facts, preferences, and what/why learnings (always say why)."
        )

    def write_shared_context(section: str, content: str, why: str) -> str:
        """Overwrite a human-owned shared-context section (project scope).

        Args:
            section: One of preferences, project, task-state, files, notes, learnings.
            content: Full new Markdown content for the section.
            why: Why this change is being made (the what/why discipline).

        Returns:
            A short status line.
        """
        if section not in SECTIONS:
            return f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}."
        changed = shared_context.write(
            section, content, author="agent", why=why, scope="project"
        )
        verb = "Updated" if changed else "No change to"
        return f"{verb} shared context '{section}' (project scope)."

    def append_shared_context(section: str, text: str, why: str) -> str:
        """Append a line to a human-owned shared-context section (project scope).

        Args:
            section: One of preferences, project, task-state, files, notes, learnings.
            text: Text to append on a new line.
            why: Why this is worth remembering.

        Returns:
            A short status line.
        """
        if section not in SECTIONS:
            return f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}."
        changed = shared_context.append(
            section, text, author="agent", why=why, scope="project"
        )
        verb = "Appended to" if changed else "No change to"
        return f"{verb} shared context '{section}' (project scope)."

    shared_context_tools = [write_shared_context, append_shared_context]

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
        tools=[*shared_context_tools, *(plugin_tools or [])],
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
            # Context, memory, and recall: tiered compaction (keeps the
            # history inside the context window), a persistent Markdown
            # notebook, and step persistence + conversation search so
            # the model can recall what compaction or an earlier run
            # dropped. Compaction is registered before Memory because
            # compaction rewrites history persistently while Memory's
            # injected block is request-only.
            *build_context_capabilities(root_dir),
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
