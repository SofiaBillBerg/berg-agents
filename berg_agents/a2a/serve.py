# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Berg's agents, served to other agents and to editors over A2A.

WHY THIS EXISTS: berg has always had ONE agent concept — the harness registry
(:class:`~berg_agents.core.harness.orchestrator.Harness`), its ``AbstractAgent``
contract, and ``_AgentCard`` carrying name, description, preferred complexity
and capabilities. What it never had was a PROTOCOL, so every caller invented
its own: the Next orchestrator drove specialists through bespoke
``start_specialist``/``answer_specialist`` tools, the chat surface had its own
transport, and neither could talk to the other. That is the "two interfaces
that don't talk" this module removes.

THE RULE THIS ENCODES: berg's registry is the source of agents, and berg's own
runs and hooks are the source of execution. A2A is the WIRE, not a second
runtime. ``fasta2a`` ships a complete server with its own storage and broker,
and adopting it would give berg a second task system beside the workflow host
it already runs — the exact duplication this module exists to avoid. So the
protocol layer is used for what it is: ``AgentCard`` for discovery, the
``AgentExecutor`` seam for the one thing berg implements, and the JSON-RPC
routes for the transport.

API note, because it cost a measurement to get right: ``a2a.types`` is the
CURRENT (v1) protobuf surface. The v0_3 names — ``TextPart``, ``Role.user``,
``TaskState.completed`` — live in ``a2a.compat`` and are NOT what a new server
uses. Here a text part is ``Part(text=...)``, the card's address is
``supported_interfaces=[AgentInterface(url=...)]`` rather than ``url=``, and the
status/artifact events are published through the SDK's own ``TaskUpdater``
rather than hand-built protobuf messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
)
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _text_of_part(part: Any) -> str | None:
    """The text a part carries, when it carries text.

    ``Part`` is a oneof over content — text, raw, url or data — so a part only
    has ``text`` when that is the branch it took, and reading it unconditionally
    would be a lie about what a binary part holds.

    :param part: One part of an incoming message.
    :return: Its text, or ``None`` when it is not a text part.
    """
    if part.WhichOneof("content") != "text":
        return None
    return part.text or ""


def _deps_for(name: str, harness: Any) -> Any:
    """The deps the named agent's tools expect, built berg's own way.

    An agent's tools read ``ctx.deps``; a run that supplies none leaves the
    agent's deps unset and every tool that touches its fields fails on a
    ``NoneType`` attribute — which is exactly what the first real turn over
    A2A hit. berg already constructs these for its own paths, so this mirrors
    them rather than inventing a second set.

    :param name: Registry name of the agent about to run.
    :param harness: The registry, consulted for the workspace root.
    :return: A deps instance for that agent, or ``None`` when it declares none.
    """
    if name == "guardian":
        from berg_agents.agents.guardian import GuardianDeps

        return GuardianDeps()
    if name in {"implementation", "planner"}:
        from berg_agents.agents.deps import AgentDeps
        from berg_agents.config.settings import get_settings

        return AgentDeps(workspace_root=get_settings().root_dir)
    return None


def _run_agent(entry: Any, harness: Any, name: str, prompt: str) -> str:
    """Run the registry entry's agent once, with the deps its tools read.

    :param entry: The registry entry (card or facade) about to run.
    :param harness: The registry, consulted for the workspace root.
    :param name: Registry name of that entry.
    :param prompt: The peer's message text.
    :return: The agent's answer text.
    """
    agent = entry.build_agent()
    deps = _deps_for(name, harness)
    result = (
        agent.run_sync(prompt, deps=deps)
        if deps is not None
        else agent.run_sync(prompt)
    )
    return str(getattr(result, "output", result))


def _prompt_from(context: RequestContext) -> str:
    """The text the peer sent, from the protocol's own message shape.

    :param context: The incoming request context.
    :return: Its message's text parts joined, or an empty string.
    """
    message = getattr(context, "message", None)
    if message is None:
        return ""
    return "\n".join(
        text
        for text in (_text_of_part(part) for part in (message.parts or []))
        if text
    )


def agent_card_for(
    info: dict[str, Any], *, name: str, base_url: str
) -> AgentCard:
    """One A2A agent card, from the registry entry berg already has.

    The card is not new information: ``_AgentCard.get_info`` and
    ``AbstractAgent.get_info`` already report a name, a description, a preferred
    complexity and capability labels. A2A spells the same facts as a card with
    skills, so this is a translation rather than a second catalog — and an
    agent that changes its capabilities in berg changes its card here with no
    second edit.

    :param info: One registry entry, as ``get_agent_info()`` reports it.
    :param name: The agent's registry name, which is also its URL segment.
    :param base_url: Where this berg serves, for the card's interface.
    :return: The agent's card.
    """
    capabilities = [
        str(capability)
        for capability in (info.get("capabilities") or [])
        if str(capability).strip()
    ]
    description = str(info.get("description") or name)
    # Each declared capability becomes a skill the other side can see, so an
    # agent that can assess risk advertises that rather than a generic "does
    # tasks". An agent with none still gets one skill rather than an empty
    # list, so the card never advertises an agent that can do nothing.
    skills = [
        AgentSkill(
            id=f"{name}:{capability}",
            name=capability,
            description=description,
            tags=capabilities,
            input_modes=["text"],
            output_modes=["text"],
        )
        for capability in (capabilities or [name])
    ]
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text"],
        default_output_modes=["text"],
        # The card's address is an interface list in v1, not a `url` field — a
        # card can describe several bindings, and berg serves one JSON-RPC one.
        supported_interfaces=[
            AgentInterface(
                url=f"{base_url}/a2a/{name}",
                protocol_binding="JSONRPC",
                # REQUIRED, and it must be "1.0": the handler answers
                # with VERSION_NOT_SUPPORTED for anything else, which is
                # how this value was found rather than guessed.
                protocol_version="1.0",
            )
        ],
        skills=skills,
    )


class BergAgentExecutor(AgentExecutor):
    """Run a berg agent's turn when a peer sends it one.

    The one implementation seam the protocol asks for: ``execute`` receives the
    peer's message and an event queue, and berg answers by running the agent it
    already knows how to run. There is deliberately no second scheduler here —
    durable sessions, gating and cancellation belong to berg's own workflow
    host, which is where every other agent's turn already lives.

    :param name: Registry name of the agent this executor serves.
    :param harness: The registry the agent is fetched from per request, so a
        newly registered agent is served without rebuilding the executor.
    """

    def __init__(self, name: str, harness: Any) -> None:
        """Store the identity of the agent this executor serves.

        :param name: Registry name of the agent.
        :param harness: The registry the agent is fetched from per request.
        """
        self.name = name
        self.harness = harness

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Run one turn and publish its result as the task's artifact.

        :param context: The peer's message and the task it belongs to.
        :param event_queue: The queue the protocol's events go on.
        """
        prompt = _prompt_from(context)

        # 1. Use the SDK's helper (or include history=[context.message] and guard for None).
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # 2. Do NOT call updater.submit() — the Task itself is already SUBMITTED.
        #    Go straight to start_work() (TASK_STATE_WORKING).
        await updater.start_work()

        try:
            # 3. Offload run_sync so it does not block the asyncio event loop
            #    while EventConsumer / ResultAggregator drains the queue.
            answer = await asyncio.to_thread(self._run, prompt)
        except Exception as exc:
            logger.warning("[a2a] agent %s failed: %s", self.name, exc)
            await updater.failed(
                _message([Part(text=f"{self.name} could not run: {exc}")])
            )
            return

        await updater.add_artifact([Part(text=answer)])
        await updater.complete(_message([Part(text=answer)]))

    # ruff: ignore[no-self-use]
    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """Report the task as cancelled.

        Berg's real cancellation lives in the workflow host (a cancelled step, a
        withdrawn gate); this reports the protocol-level outcome so a peer that
        cancels is answered honestly rather than left watching a task that will
        never finish.

        :param context: The task being cancelled.
        :param event_queue: The queue the protocol's events go on.
        """
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel(_message([Part(text="Cancelled.")]))

    def _run(self, prompt: str) -> str:
        """Run this agent's turn through berg's own agent builder.

        Only the agents berg can build a pydantic-ai agent for are served. A
        registry entry that is a display card without a builder refuses rather
        than pretending to run — an interface that answers for an agent it
        cannot run is worse than one that says so.

        :param prompt: The peer's message text.
        :return: The agent's answer text.
        :raises NotImplementedError: When this entry has no builder yet.
        """
        entry = self.harness.get_agent(self.name)
        if not hasattr(entry, "build_agent"):
            raise NotImplementedError(
                f"Agent {self.name!r} is a catalog card with no builder on the "
                "A2A path yet; register a builder for it rather than serving a "
                "turn that cannot run."
            )
        return _run_agent(entry, self.harness, self.name, prompt)


def _message(parts: list[Any]) -> Any:
    """An agent-authored message, for the protocol's status events.

    :param parts: The message's parts.
    :return: A message in the shape ``TaskUpdater`` expects.
    """
    import uuid

    from a2a.types import Message, Role

    return Message(
        role=Role.ROLE_AGENT, parts=parts, message_id=uuid.uuid4().hex
    )


def serve_berg_agents(app: FastAPI, *, harness: Any, base_url: str) -> None:
    """Serve every berg agent over A2A, from the registry it already has.

    One route set per agent at ``/a2a/<name>``, each with its own card — which
    is A2A's own shape: an agent is addressable where its card lives. Nothing
    here registers an agent by hand; a new registry entry is served because it
    is in the registry, which is the whole point of doing this from
    ``get_agent_info()`` rather than from a list maintained by this module.

    :param app: berg's FastAPI application.
    :param harness: The registry to serve.
    :param base_url: Where this berg serves, for every card's interface.
    """
    for info in harness.get_agent_info():
        name = str(info.get("name") or "").strip()
        if not name:
            continue
        card = agent_card_for(info, name=name, base_url=base_url)
        handler = DefaultRequestHandler(
            agent_executor=BergAgentExecutor(name, harness=harness),
            task_store=InMemoryTaskStore(),
            agent_card=card,
        )
        add_a2a_routes_to_fastapi(
            app,
            agent_card_routes=create_agent_card_routes(
                card, card_url=f"/a2a/{name}/.well-known/agent-card.json"
            ),
            jsonrpc_routes=create_jsonrpc_routes(
                handler, rpc_url=f"/a2a/{name}"
            ),
        )
        logger.info("[a2a] serving agent %s at /a2a/%s", name, name)
