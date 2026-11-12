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
from pathlib import Path
from typing import Any

from berg_agents.agents.deps import AgentDeps
from berg_agents.core.tool_spec import fill_tool_inventory

logger = logging.getLogger(__name__)


def _delegation_gate_enabled() -> bool:
    """Whether a delegated task asks the user before it starts.

    Kill-switch for deployments where the user has already accepted
    delegation and a card per task is noise: set
    ``BERG_DELEGATION_GATE=off``. Absent or any other value means on,
    because a delegated implementer's writes are ungated and "off" is the
    setting that needs a reason.

    :return: True when delegations pause for approval.
    """
    return os.getenv("BERG_DELEGATION_GATE", "").strip().lower() not in {
        "off",
        "0",
        "false",
        "no"}


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


def authored_capabilities_dir() -> Path:
    """Directory holding runtime-authored capabilities.

    Deliberately the **global** config dir, not the project one: the
    harness requires the authored files to sit outside the workspace, or
    the model could rewrite them (and ``manifest.json``) with its own
    file tools and skip the validation ``author_capability`` performs. A
    project-local directory would be inside the workspace by definition.

    :return: ``~/.berg-agents/authored`` (``BERG_AGENTS_CONFIG_DIR``
        overrides the root).
    """
    from berg_agents.config.paths import global_config_dir

    return global_config_dir() / "authored"


def build_chat_agent(
    model_id: str | None = None,
    *,
    root_dir: str = ".",
    plugin_tools: list[Any] | None = None,
    disabled_mcp: frozenset[str] = frozenset(),
    disabled_skills: frozenset[str] = frozenset(),
    active_agent: str | None = None,
    active_agent_description: str | None = None,
    session_id: str | None = None,
    instructions: str | None = None,
    spec: Any | None = None,
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
    :param plugin_tools: Tools the ``chat`` role may use, already
        resolved and session-bound by :func:`plugin_system.get_chat_plugin_state`;
        pass ``None`` (or omit) for a plugin-free agent. It is handed in
        rather than fetched here so tool membership and session binding
        are decided in one place.
    :param disabled_mcp: MCP server keys to withhold (disabled toggles).
    :param disabled_skills: Chat skill ids (``skill-<name>``) to withhold.
    :return: A configured ``Agent`` ready for ``VercelAIAdapter``.
    """
    from pathlib import Path

    from berg_agents.agents.delegation import build_delegation_capabilities
    from berg_agents.agents.factory import create_tools
    from berg_agents.agents.workspace_toolset import WorkspaceToolset
    from berg_agents.capabilities.context_capabilities import (
        build_context_capabilities,
    )
    from berg_agents.capabilities.delegation_gate import DelegationApprovalGate
    from berg_agents.capabilities.mcp_toolsets import build_mcp_toolsets
    from berg_agents.capabilities.runaway_guard import RunawayGuard
    from berg_agents.capabilities.skills import load_skill_capabilities
    from berg_agents.capabilities.turn_shape import build_turn_shape_capability
    from berg_agents.capabilities.wall_clock_guard import WallClockGuard
    from berg_agents.capabilities.web_backends import (
        make_web_fetch,
        make_web_search,
    )
    from berg_agents.config.settings import get_settings
    from berg_agents.core.shared_context import SECTIONS, SharedContext
    from berg_agents.providers.models import (
        resolve_model_instance,
        resolve_model_request_settings,
    )
    from pydantic_ai import Agent
    from pydantic_ai.capabilities import LocalWorkspace, WebFetch, WebSearch
    from pydantic_ai_harness.ask_user import AskUser
    from pydantic_ai_harness.capability_creation import CapabilityCreation
    from pydantic_ai_harness.guardrails import GuardrailResult, ToolGuardrail

    # Resolve the model from .berg-agents - resolve_model_instance reads
    # bergagents.jsonc and returns a fully-configured OpenAIChatModel.
    model = resolve_model_instance(model_id or "")
    # Per-model request options (a chat_template override for strict
    # templates, for example) ride in extra_body: they are request
    # payload, not client construction, so they cannot live on the model.
    extra_body = resolve_model_request_settings(model_id or "")

    # Build the system prompt from settings (config-driven, not hardcoded).
    settings = get_settings()
    # An explicit instructions string replaces the configured base prompt:
    # a spec-defined agent carries its own, and the operational blocks
    # below (shared context, ask_user contract) still apply to it.
    system_prompt = (
        instructions
        if instructions is not None
        else (
            settings.system_prompt.format(root_dir=root_dir)
            if f"{root_dir}" in settings.system_prompt
            else settings.system_prompt
        )
    )
    # The tool inventory's placeholder is filled from the specs THIS agent is
    # actually built with, so the prompt cannot name a tool or a parameter the
    # toolset does not have. Generated, never hand-maintained: a hand-written
    # list goes stale, and a stale list makes the model send keys the tools
    # reject - which is the stall this replaced.
    system_prompt = fill_tool_inventory(system_prompt, create_tools(root_dir))

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

    # Shared Context: the shared foundation this agent leverages.
    # Rendered fresh per request (this builder runs per /api/chat/stream),
    # project scope shadowing global. The block below is the read path;
    # the two tools are the contribute path (author + why recorded).
    # ``root_dir`` arrives as a str (it is interpolated into the prompt
    # above); the resolver takes a Path, so convert once here rather than
    # rely on the callee tolerating either.
    shared_context = SharedContext.resolve(Path(root_dir))
    rendered_context = shared_context.render()
    if rendered_context:
        system_prompt += (
            "\n\n# Shared context (shared knowledge with the user; project "
            "shadows global)\n"
            f"{rendered_context}\n\n"
            "This is shared working context, kept as plain files that both "
            "you and the user read and contribute to. Read it first; it "
            "holds preferences, knowledge, research, work-notes, task-state, "
            "files, notes and learnings. Keep it current: use "
            "write_shared_context / append_shared_context to record durable "
            "facts, preferences, knowledge, research findings, work notes, "
            "and what/why learnings (always say why). When something durable "
            "turns out to be true, write it here instead of establishing "
            "it again later."
        )

    # The ask_user_question schema is strict (extra fields are rejected) and
    # its limits are short, but nothing in the model's context states them:
    # an underspecified call fails validation, is retried verbatim, and the
    # run dies at the retry limit. State the contract explicitly, taken from
    # the harness constants so the text cannot drift from what is enforced.
    try:
        from pydantic_ai_harness.ask_user._types import (
            MAX_HEADER_LENGTH,
            MAX_OPTIONS,
            MAX_QUESTION_LENGTH,
            MIN_OPTIONS,
        )

        system_prompt += (
            "\n\n# ask_user_question\n"
            "Call `ask_user_question` only when you genuinely cannot proceed "
            "without an answer, and keep the call strictly to this shape:\n"
            "`ask_user_question(questions=[{header, question, options, "
            "multi_select}])`\n"
            "Each question object has exactly these keys:\n"
            f"- header: short label, at most {MAX_HEADER_LENGTH} characters, "
            "must be unique within the call (it is the answer's key).\n"
            f"- question: the full question text, at most "
            f"{MAX_QUESTION_LENGTH} characters.\n"
            f"- options: {MIN_OPTIONS} to {MAX_OPTIONS} choices, each "
            "{label, description}; labels must be unique and at most 50 "
            "characters.\n"
            "- multi_select: true or false.\n"
            "Do NOT add any other key (for example `id` or `tool`); unknown "
            "keys are rejected. Ask in prose instead of calling the tool when "
            "a short clarifying sentence would do."
        )
    except Exception:  # NOTE: never let prompt text break agent build.
        pass

    def write_shared_context(section: str, content: str, why: str) -> str:
        """Overwrite a shared-context section (project scope).

        Args:
            section: One of preferences, project, task-state, files, notes, router_stats.
            content: Full new Markdown content for the section.
            why: Why this change is being made (what/why discipline).

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
        """Append a line to a shared-context section (project scope).

        Args:
            section: One of preferences, project, task-state, files, notes, router_stats.
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

    # Shared workspace root for file tools and subagent delegates. The
    # plan tools are the session-bound ones from the todo plugin: the
    # staged delegates write and read the plan there, so it is the same
    # list the user edits — one plan authority, not a string passed from
    # stage to stage.
    plan_tools = {
        getattr(tool, "name", ""): getattr(tool, "function", tool)
        for tool in (plugin_tools or [])
        if getattr(tool, "name", "")
    }
    toolset = WorkspaceToolset(
        root_dir, allow_shell=_shell_allowed(), plan_tools=plan_tools
    )

    # A spec agent is assembled by pydantic-ai's own from_spec, so its
    # declared capabilities (WebSearch, Thinking, an MCP server, ...) are
    # built by the library and MERGED with berg's list below - one
    # assembly path, with the spec as the source of the agent's own
    # choices. Everything berg needs stays identical: the model always
    # comes from berg's provider registry, never a provider-name string
    # pydantic-ai would have to guess.
    # ``output_type``, ``usage_limits`` and the deferred-tool output are
    # NOT set here: the chat endpoint passes them per run, and from_spec
    # accepts no such keyword.
    agent_kwargs: dict[str, Any] = {
        "model": model,
        "deps_type": AgentDeps,
        "system_prompt": system_prompt,
        "tool_timeout": 30,
        # Two output retries so one malformed tool call gets a
        # recovery chance instead of failing the whole turn.
        # NOTE: no approval-handling capability here on purpose.
        # Tools flagged requires_approval (bash, edit_file,
        # write_file, implement_task) pause the run as
        # DeferredToolRequests; the chat endpoint declares that
        # output type so the VercelAIAdapter streams an approval
        # request, and the frontend answers it with an approval
        # response. Every approval is collected through the UI.
        # Output retries cover malformed final answers. Tool retries get
        # their own, larger budget: a wrong tool call is usually a schema
        # mistake the model can fix when it sees the validation error, and
        # the library default of 1 kills the whole run on the first miss.
        "retries": {"output": 3, "tools": 3},
        # Per-model request options as extra_body (e.g. a strict chat
        # template override). None when the model declares none, so the
        # provider's own defaults apply byte-for-byte.
        "model_settings": {"extra_body": extra_body} if extra_body else None,
        # NOTE: Enabled plugin tools (shared-todo pilot). Empty by
        # default — low-risk tools need no HITL approval.
        "tools": [*shared_context_tools, *(plugin_tools or [])],
        "toolsets": [toolset, *build_mcp_toolsets(exclude=disabled_mcp)],
        "capabilities": [
            # Turn-shape normalizer: one user turn per request. Strict
            # chat templates (Mistral/Devstral's Unsloth template) reject
            # two user turns in a row with a Jinja 500, and the memory
            # snapshot plus steering text produce exactly that shape.
            # Registered first so every later capability — compaction
            # included — sees the normalized history.
            *([cap] if (cap := build_turn_shape_capability()) else []),
            # Provider-adaptive web tools: provider-native first where
            # the model supports it, local implementation otherwise.
            # The local side tries the configured web backends in
            # order (settings.web_search_backends, default
            # ollama → duckduckgo → direct).
            WebSearch(local=make_web_search(settings.web_search_backends)),
            WebFetch(local=make_web_fetch(settings.web_search_backends)),
            # NOTE: There is deliberately no ``Planning`` capability here.
            # The plan is owned by shared-todo, whose tools arrive in
            # ``plugin_tools`` and whose list the user can edit. A
            # second, model-only plan store would give the session two
            # plans that can disagree — one the user can see and change,
            # one they cannot.
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
            ],
            # Let the model ask the user a question mid-run. With no
            # answerer the call defers, so the run pauses as a
            # DeferredToolRequests and the answer comes back through the
            # same approval batch as every other user decision - one
            # HITL surface, not a second one.
            AskUser(answerer=None),
            # Two-stage check-in so a run cannot go on indefinitely
            # without the user having a say: an advisory reminder at the
            # configured limit, and a forced approval pause at twice it.
            # The count is persisted per session (the agent is rebuilt per
            # request) and is reset only when the agent yields control.
            RunawayGuard(
                limit=settings.runaway_tool_call_limit, session_id=session_id
            ),
            # Wall-clock ceiling: a run that has been executing past the
            # configured duration pauses on the next tool call, through the
            # same approval card as every other user decision. The count
            # guard above bounds *unattended tool calls*; this bounds *time*
            # (a slow provider, a tool that waits). Approving restarts the
            # clock, so a long session continues one stretch at a time.
            WallClockGuard(
                limit_seconds=settings.run_max_duration_minutes * 60
            )]}
    # Runtime capability authoring. Three pieces, in this order:
    #   1. a writable LocalWorkspace, without which the harness refuses to
    #      start the run at all (it must know the code runs on this
    #      machine, not in a sandbox the model could escape);
    #   2. CapabilityCreation itself, whose tools let the model write,
    #      list and disable capabilities for the NEXT run;
    #   3. a guardrail that sends every authoring and disabling call
    #      through the user approval batch - model-written Python runs
    #      in this process, so nothing executes unseen.
    # The authored directory lives in the GLOBAL config dir on purpose:
    # it must sit outside the workspace, or the model could edit the
    # authored files and manifest with its own file tools and bypass
    # validation entirely.
    agent_kwargs["capabilities"].extend([
        LocalWorkspace(root_dir),
        CapabilityCreation(directory=authored_capabilities_dir()),
        ToolGuardrail(
            guard=lambda _call: GuardrailResult.approve(),
            tools=[
                "author_capability",
                "list_authored_capabilities",
                "disable_authored_capability"],
        )])
    # Delegation, with task control: the implementer runs as a task the
    # parent can steer, ask, and stop. It sits beside the staged
    # delegates on purpose (phase 1 of the migration): the hand-rolled
    # implement_task is retired only once this path is verified live.
    agent_kwargs["capabilities"].extend(
        build_delegation_capabilities(plan_tools)
    )
    # A delegated implementer's writes are ungated, so the gate is on the
    # delegation itself - the one the staged implement_task carried.
    agent_kwargs["capabilities"].append(
        DelegationApprovalGate(enabled=_delegation_gate_enabled())
    )
    # from_spec takes the spec first and merges the spec's own
    # capabilities with berg's list above; the model is always berg's
    # provider-registry instance, never a provider-name string.
    agent = (
        Agent.from_spec(spec, **agent_kwargs)
        if spec is not None
        else Agent(**agent_kwargs)
    )

    return agent
