"""One chat turn, hosted durably — phase 1c, slice a.

This is the first slice of the swap: berg's **real** chat agent (the one
``build_chat_agent`` assembles — its toolset, plan store, capabilities and
persona) running inside the durable workflow host, and its frames reaching the
client through the encoder berg already uses. That is deliberate: the wire the UI
renders is one wire, and this slice does not invent a second one.

What this slice is NOT, named so it cannot quietly become a claim:

* approvals, steering, the delegation tree, persistence and Stop are still
  ``LiveRun``'s — those are slices b to e;
* the plugin toolset is not carried across, because a tool object cannot cross a
  step boundary. The agent here is built from serialisable arguments only.

So this is the temporary second run host, and ``_TEMPORARY_HOST`` is the flag that
says so out loud until slice f deletes it.
"""

from __future__ import annotations

from typing import Any

from berg_agents.workflow.registry import wf
import pydantic
from vercel import workflow

#: True while slices b to e are unfinished, which is what makes this a second run
#: host rather than the only one. Slice f deletes this module; until then the
#: flag is the reminder that the duplicate is temporary and must not spread.
_TEMPORARY_HOST = True


class Frame(pydantic.BaseModel):
    """One SSE frame, byte-for-byte as berg's encoder produced it.

    Stored on the durable stream so a reader that joins late, or a restarted
    server, replays exactly the frames the turn produced.
    """

    data: str


@wf.step(cancellable=True)
async def agent_turn(
    *,
    writable: workflow.WorkflowWritable[Frame],
    prompt: str,
    model_id: str,
    root_dir: str,
    active_agent: str | None,
    active_agent_description: str | None,
) -> dict[str, Any]:
    """Run berg's real chat agent, and publish its frames as they are encoded.

    The agent is built *inside* the step from serialisable arguments, because a
    tool object cannot cross a step boundary. That is the one thing this step
    gives up against ``_session_agent``: the plugin toolset rides along in 1c-e,
    not here.

    :param writable: This turn's durable frame stream.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: What the turn produced, for the run's return value.
    """
    from berg_agents.agents.chat_agent import build_chat_agent
    from berg_agents.ui.route_handlers.chat import encode_run_stream

    agent = build_chat_agent(
        model_id,
        root_dir=root_dir,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )

    frames = 0
    # `agent.iter` is an async CONTEXT MANAGER in this pydantic-ai (2.66.0), not
    # a generator: `async with agent.iter(...) as run`. Handing it to an
    # `async for` is the "'async for' requires an object with __aiter__" that
    # failed this slice three times, and `AgentRun.next()` wants the node
    # explicitly.
    #
    # The walk reuses berg's own helpers (`_is_end`, `_node_emits_events`,
    # `_node_events`, `_run_result_event`) and feeds the encoder ONE iterator of
    # native events, because the protocol's start/finish frames bracket a whole
    # turn — calling the encoder per event brackets every event and duplicates
    # the wire.
    from berg_agents.ui.run_registry import (
        _is_end,
        _node_emits_events,
        _node_events,
        _run_result_event,
    )

    async def _events() -> Any:
        """The turn's native events in graph order, ending with its result."""
        async with agent.iter(prompt, deps=_deps(root_dir)) as run:
            node = run.next_node
            while not _is_end(node):
                # Only model-call and tool nodes emit protocol events. Streaming
                # a node that emits none (UserPromptNode, for one) fails inside
                # the encoder.
                if _node_emits_events(node):
                    async for event in _node_events(node, run.ctx):
                        yield event
                node = await run.next(node)
            # The encoder closes the turn on the run's result event; without it
            # the turn ends without the frames that describe how it ended.
            yield _run_result_event(getattr(run, "result", None))

    async for frame in encode_run_stream(_events()):
        await writable.write(Frame(data=frame))
        frames += 1
    return {"frames": frames}


def _deps(root_dir: str) -> Any:
    """The run's shared deps: the same ``AgentDeps`` the chat path builds."""
    from berg_agents.agents.deps import AgentDeps

    return AgentDeps(workspace_root=root_dir)


@wf.workflow
async def chat_turn(
    *,
    token: str,
    prompt: str,
    model_id: str,
    root_dir: str,
    active_agent: str | None = None,
    active_agent_description: str | None = None,
) -> dict[str, Any]:
    """One chat turn, durable.

    :param token: Namespace for this turn's hooks and streams.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: The turn's outcome, readable from a fresh ``Run`` handle.
    """
    # The frames live in the run's own default namespace: the run id already
    # namespaces them, and a second namespace would have to be discovered by
    # every reader. The token stays what it is for - this turn's hooks.
    stream = workflow.get_writable(type=Frame)
    outcome = await agent_turn(
        writable=stream,
        prompt=prompt,
        model_id=model_id,
        root_dir=root_dir,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )
    # Closing is a step's job: a workflow body may not touch the stream.
    await close_stream(writable=stream)
    return outcome


@wf.step
async def close_stream(*, writable: workflow.WorkflowWritable[Frame]) -> None:
    """Close the frame stream so readers know the turn is over."""
    await writable.close()
