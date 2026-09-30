"""Pydantic AI adapter for BergAgents tools and agent construction.

Builds a :class:`~pydantic_ai.Agent` whose tools come from a single
:class:`~berg_agents.agents.workspace_toolset.WorkspaceToolset` — one
named, audited toolset wrapping the framework-free ``ToolSpec`` list
(which the harness loop uses directly) plus the ``run_task`` pipeline
delegate. Used by the ``VercelAIAdapter`` streaming endpoint.
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
    """
    return (
        os.getenv("BERG_AGENT_ALLOW_SHELL", "true").strip().lower()
        not in {"0", "false", "no", "off"}
    )


def build_chat_agent(
    model_id: str | None = None,
    *,
    root_dir: str = ".",
) -> Any:
    """Build a pydantic_ai ``Agent`` for the streaming chat endpoint.

    The agent receives a single
    :class:`~berg_agents.agents.workspace_toolset.WorkspaceToolset`
    (id ``"workspace"``): file/shell tools plus the ``run_task``
    harness delegate, with per-tool approval flags and a usage guide
    carried by the toolset itself.

    System prompt, model, and temperature all come from configuration
    (``config/bergagents.jsonc`` and ``config/profiles.yaml``) - never
    hardcoded.

    :param model_id: Model identifier to resolve; falls back to the session's
        or settings' default.
    :param root_dir: Workspace root for file tools.
    :return: A configured ``Agent`` ready for ``VercelAIAdapter``.
    """
    from berg_agents.agents.workspace_toolset import WorkspaceToolset
    from berg_agents.config.settings import get_settings
    from berg_agents.core.harness import Harness
    from berg_agents.capabilities.skills import load_skill_capabilities
    from berg_agents.providers.models import resolve_model_instance
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import WebFetch, WebSearch

    # Resolve the model from config - resolve_model_instance reads
    # bergagents.jsonc and returns a fully-configured OpenAIChatModel.
    model = resolve_model_instance(model_id or "")

    # Build the system prompt from settings (config-driven, not hardcoded).
    settings = get_settings()
    system_prompt = (
        settings.system_prompt.format(root_dir=root_dir)
        if "{root_dir}" in settings.system_prompt
        else settings.system_prompt
    )

    # Shared harness for the run_task delegate - full pipeline
    # (planning, subagents, HITL, implementation).
    harness = Harness(enable_inference=True)

    toolset = WorkspaceToolset(
        root_dir,
        harness=harness,
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
        # write_file, run_task) pause the run as DeferredToolRequests;
        # the chat endpoint declares that output type so the
        # VercelAIAdapter streams an approval request, and the
        # frontend answers it with an approval response. Approving
        # happens in the UI — never silently.
        retries={"output": 3},
        toolsets=[toolset],
        capabilities=[
            # Provider-adaptive web tools, LOCAL-only: native tools
            # need the Responses API + provider-side infrastructure
            # (absent on Ollama/Unsloth/OpenAI-compatible endpoints),
            # so force the in-process fallbacks. Identical behavior
            # on every configured provider. Eager (not deferred):
            # two small tools the model should always see.
            WebSearch(native=False, local="duckduckgo"),
            WebFetch(native=False, local=True),
            # Repo skills (SKILL.md manuals) as deferred capabilities:
            # one-line catalog entries until the model loads one.
            # Point BERG_AGENT_SKILLS at e.g. ".agents/skills".
            *load_skill_capabilities(settings.skills, root_dir=root_dir)],
    )

    return agent
