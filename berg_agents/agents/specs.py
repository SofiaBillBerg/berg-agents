# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Declarative agent specs, loaded from ``.berg-agents/agents/``.

An agent used to be something you could only get by writing Python: the
built-in roles are builder functions, and the harness registry holds
objects. This module closes that gap with pydantic-ai's own
:class:`~pydantic_ai.AgentSpec`, so an agent is a validated YAML file::

    # .berg-agents/agents/reviewer.yaml
    model: unsloth/devstral-small-2-24b
    name: reviewer
    description: Reviews a diff for correctness and risk.
    instructions: |
      You review changes. Read before you judge...

The model is resolved through berg's own provider registry (never a
``provider:model`` string pydantic-ai would have to guess), and the agent
keeps every built-in capability - the workspace toolset, the todo-backed
plan store, compaction, memory, HITL guards - because it is assembled by
the same :func:`~berg_agents.agents.chat_agent.build_chat_agent` as the
default chat agent. One assembly path, not a second one.

Discovery is deliberately forgiving: a malformed spec is logged with its
file name and skipped, never fatal, because a broken agent file must not
stop the server (or the other agents) from coming up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Subdirectory of the resolved config dir that holds agent specs.
SPEC_DIR_NAME = "agents"

#: Extensions treated as specs (YAML is a JSON superset, so ``.json``
#: specs load through the same reader).
SPEC_SUFFIXES = (".yaml", ".yml", ".json")


@dataclass
class SpecAgent:
    """One spec-defined agent, as a berg agent facade.

    Implements just enough of :class:`~berg_agents.core.interface.AbstractAgent`
    to live in the harness registry: ``get_info`` feeds ``/api/agents``
    and the selector, ``can_handle`` reports that selection is explicit
    (routing never picks a spec agent), and ``build_agent`` assembles the
    pydantic-ai agent the chat endpoint runs.

    Attributes:
        name: Registry key (the spec's ``name``, else the file stem).
        description: One-line description for the UI.
        model_id: Model id as declared in berg's providers block.
        instructions: The agent's system prompt.
        source: File the spec was read from (for logs and errors).
        settings: Per-model request settings (``model_settings`` block).
    """

    name: str
    description: str
    model_id: str | None
    instructions: str | None
    source: Path
    spec: Any = None
    settings: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def can_handle(task: dict[str, Any]) -> float:
        """Report whether this agent should pick up a routed task.

        Spec agents are selected explicitly by the user through
        ``/api/agents/active``; the router never assigns one, so the
        confidence is zero and routing is unchanged.

        :param task: Task dictionary (unused).
        :return: ``0.0`` — never routed to.
        """
        return 0.0

    def execute(
        self, task: dict[str, Any], context: Any, model: Any = None
    ) -> Any:
        """Refuse to run outside the chat path.

        A spec agent is a chat agent: it runs through the streaming chat
        endpoint, which assembles it with :meth:`build_agent`. Running it
        here would need a second assembly path, which is the duplication
        this design avoids.

        :param task: Task dictionary (unused).
        :param context: Task context (unused).
        :param model: Model instance (unused).
        :raises NotImplementedError: Always - use the chat endpoint.
        """
        raise NotImplementedError(
            f"Spec agent {self.name!r} runs through the chat endpoint, "
            "not the task router."
        )

    def get_info(self) -> dict[str, Any]:
        """Return registry info for ``/api/agents`` and the selector.

        :return: Info mapping mirroring the built-in agents' shape.
        """
        return {
            "name": self.name,
            "description": self.description,
            "preferred_complexity": "standard",
            "capabilities": ["spec"],
            "source": str(self.source)}

    def build_agent(self, **kwargs: Any) -> Any:
        """Assemble the pydantic-ai agent this spec describes.

        Delegates to the one chat-agent builder so a spec agent keeps the
        workspace toolset, the plan store, and every capability the
        default agent has - and so its own declared capabilities (WebSearch,
        Thinking, an MCP server) are built by pydantic-ai's ``from_spec``
        and merged with berg's, rather than re-implemented here.

        :param kwargs: Forwarded to ``build_chat_agent`` (root dir,
            plugin tools, disabled sets, session id).
        :return: A configured ``Agent``.
        """
        from berg_agents.agents.chat_agent import build_chat_agent

        return build_chat_agent(
            self.model_id,
            instructions=self.instructions,
            active_agent=self.name,
            active_agent_description=self.description,
            spec=self.spec,
            **kwargs,
        )


def spec_dir() -> Path:
    """Directory agent specs are read from.

    :return: ``<resolved config dir>/agents`` (not created here).
    """
    from berg_agents.config.paths import resolve_config_dir

    return resolve_config_dir() / SPEC_DIR_NAME


def _spec_from_file(path: Path) -> Any | None:
    """Read one spec file, or ``None`` when it cannot be parsed.

    :param path: YAML/JSON file to read.
    :return: An ``AgentSpec``, or ``None`` on any failure.
    """
    try:
        from pydantic_ai import AgentSpec

        return AgentSpec.from_file(path)
    except ImportError:  # pragma: no cover - older pydantic-ai
        logger.warning(
            "Agent spec %s skipped: this pydantic-ai has no AgentSpec support",
            path.name,
        )
        return None
    except Exception as exc:
        # A malformed spec is the file's fault, not the server's: skip it
        # with enough detail to fix, and keep every other agent.
        logger.warning("Agent spec %s skipped: %s", path.name, exc)
        return None


def load_specs(directory: Path | None = None) -> list[SpecAgent]:
    """Load every agent spec in *directory*, failing soft per file.

    :param directory: Directory to read; defaults to :func:`spec_dir`.
    :return: Valid spec agents, sorted by name (stable registration).
    """
    root = Path(directory) if directory is not None else spec_dir()
    if not root.is_dir():
        return []
    specs: list[SpecAgent] = []
    for path in sorted(root.iterdir()):
        if path.suffix not in SPEC_SUFFIXES or not path.is_file():
            continue
        spec = _spec_from_file(path)
        if spec is None:
            continue
        name = (getattr(spec, "name", None) or path.stem).strip()
        if not name:
            logger.warning("Agent spec %s skipped: no name", path.name)
            continue
        description = str(getattr(spec, "description", "") or "").strip()
        instructions = getattr(spec, "instructions", None)
        model_id = getattr(spec, "model", None)
        settings = getattr(spec, "model_settings", None) or {}
        # A spec whose model berg cannot resolve is still loadable - the
        # default model applies - but say so, because running the agent
        # would otherwise fail on a name nobody declared.
        if model_id:
            from berg_agents.providers.registry import resolve_model

            try:
                resolve_model(str(model_id))
            except KeyError:
                logger.warning(
                    "Agent spec %s: model %r is not declared in any "
                    "provider block; the default model will be used.",
                    path.name,
                    model_id,
                )
                model_id = None
        specs.append(
            SpecAgent(
                name=name,
                description=description,
                model_id=str(model_id) if model_id else None,
                instructions=(
                    str(instructions) if instructions is not None else None
                ),
                source=path,
                spec=spec,
                settings=dict(settings) if isinstance(settings, dict) else {},
            )
        )
    return specs


def register_spec_agents(harness: Any, directory: Path | None = None) -> int:
    """Register every spec agent into the harness registry.

    A name a built-in agent already owns is skipped rather than
    shadowed: the built-in is code someone tested, and a file silently
    replacing it would be surprising.

    :param harness: The harness to register into.
    :param directory: Directory to read; defaults to :func:`spec_dir`.
    :return: How many agents were registered.
    """
    registered = 0
    for spec_agent in load_specs(directory):
        existing = getattr(harness, "get_agent", None)
        if callable(existing):
            try:
                existing(spec_agent.name)
                logger.info(
                    "Agent spec %s skipped: %r is already registered",
                    spec_agent.source.name,
                    spec_agent.name,
                )
                continue
            except KeyError:
                pass
        harness.register_agent(spec_agent.name, spec_agent)
        registered += 1
    if registered:
        logger.info("Registered %d agent spec(s)", registered)
    return registered
