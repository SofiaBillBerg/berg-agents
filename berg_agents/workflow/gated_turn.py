"""A gated write on the durable host — phase 1c, slice b.

The write gate is what the whole port exists to serve (*the AI must never run
loose*). On ``LiveRun`` it is a process-local future keyed by call id, answered
by ``POST /api/chat/delegation-approval``. On the durable host the gate is a
**hook**: the workflow body waits, the answer endpoint resumes it, and the
decision survives the process.

The shape is forced by where a hook may be waited. A hook belongs in a workflow
BODY, never in a step, so the tool call happens in a step that *reports* what is
pending, the body waits, and the step is called again carrying the decision:

    pending = await agent_step(...)                # emits the approval card
    while pending:
        decision = await WriteGate.wait(token)     # the body; the endpoint resumes
        pending = await agent_step(..., history=..., deferred=decision)

Each pass carries the turn's history, because a resumed pass is the same turn
continued rather than a new one — which is why the step takes and returns
``history`` rather than re-issuing the prompt.

The frames for berg's approval card come free: the agent's own encoder emits the
approval-request chunk when it sees the ``DeferredToolRequestsEvent``, and those
frames land on the durable stream beside the text frames.
"""

from __future__ import annotations

from typing import Any

from berg_agents.workflow.chat_turn import Frame
from berg_agents.workflow.registry import wf
import pydantic
from vercel import workflow


class WriteGate(pydantic.BaseModel, workflow.BaseHook):
    """The user's decision on the gated write."""

    decision: str  # "approved" | "rejected"
    reason: str | None = None


def _serialise_history(messages: Any) -> list[dict[str, Any]]:
    """A turn's messages as plain dicts, so a step boundary can carry them."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    if not messages:
        return []
    return list(ModelMessagesTypeAdapter.dump_python(messages, mode="json"))


def _restore_history(rows: list[dict[str, Any]]) -> Any:
    """The inverse, for the pass that resumes a paused turn."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    if not rows:
        return None
    return ModelMessagesTypeAdapter.validate_python(rows)


@wf.step(cancellable=True)
async def agent_step(
    *,
    writable: workflow.WorkflowWritable[Frame],
    prompt: str,
    model_id: str,
    root_dir: str,
    history: list[dict[str, Any]],
    deferred: Any,
    active_agent: str | None,
    active_agent_description: str | None,
) -> dict[str, Any]:
    """One pass of the turn: model calls and tools, or a paused gate.

    No ``HandleDeferredToolCalls`` capability is registered on this agent
    deliberately — with one, a gated call would be answered *inside* the run and
    the body could never wait for the user. Without one the run ends on
    ``DeferredToolRequests`` and the decision travels back here.

    :param writable: This turn's durable frame stream.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param history: The turn so far, for a resumed pass.
    :param deferred: The user's decision, or ``None`` on the first pass.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: The turn's history, whatever is pending at the gate, and the frame
        count this pass produced.
    """
    from berg_agents.agents.chat_agent import build_chat_agent
    from berg_agents.agents.deps import AgentDeps
    from berg_agents.ui.route_handlers.chat import encode_run_stream
    from pydantic_ai.messages import DeferredToolRequests

    agent = build_chat_agent(
        model_id,
        root_dir=root_dir,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )
    # Imported here, not at module level: the workflow body's module is
    # re-imported inside the runtime's deterministic sandbox, and pydantic_ai's
    # own import chain reaches os.urandom(), which that sandbox refuses. This is
    # the same wall the lazy package root cleared for the whole berg package.

    kwargs: dict[str, Any] = {
        "deps": AgentDeps(workspace_root=root_dir),
        # A gated tool pauses the run as output instead of executing.
        "output_type": [str, DeferredToolRequests]}
    restored = _restore_history(history)
    if restored is not None:
        kwargs["message_history"] = restored
    if deferred is not None:
        kwargs["deferred_tool_results"] = deferred

    from berg_agents.ui.run_registry import (
        _is_end,
        _node_emits_events,
        _node_events,
        _run_result_event,
    )

    seen: dict[str, Any] = {"result": None, "messages": []}

    async def _events() -> Any:
        """This pass's native events in graph order, ending with its result.

        One iterator for the encoder, because its start/finish frames bracket a
        whole turn — feeding it per event duplicates the wire. It also records
        the outcome it saw, so the pass is walked once and not twice: re-running
        the agent to read its result would spend the model's answer twice.
        """
        async with agent.iter(prompt, **kwargs) as run:
            node = run.next_node
            while not _is_end(node):
                if _node_emits_events(node):
                    async for event in _node_events(node, run.ctx):
                        yield event
                node = await run.next(node)
            seen["result"] = getattr(run, "result", None)
            seen["messages"] = run.all_messages()
            yield _run_result_event(seen["result"])

    frames = 0
    async for frame in encode_run_stream(_events()):
        await writable.write(Frame(data=frame))
        frames += 1

    pending: list[dict[str, Any]] = []
    # Naming this type at module level would pull pydantic_ai into the workflow
    # body's import chain, which the runtime's deterministic sandbox refuses.
    from pydantic_ai.messages import DeferredToolRequests

    result = seen["result"]
    if isinstance(result, DeferredToolRequests):
        for call in result.approvals:
            pending.append({
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args_as_dict()})
        requests = result
    else:
        requests = None

    return {
        "history": _serialise_history(seen["messages"]),
        "pending": pending,
        "requests": (
            _serialise_requests(requests) if requests is not None else None
        ),
        "frames": frames}


def _serialise_requests(requests: Any) -> dict[str, Any]:
    """The pending gate as plain dicts, so the body can rebuild decisions.

    ``requests`` is a ``DeferredToolRequests``; it is read through ``Any`` so
    that naming its type at module level does not pull pydantic_ai into the
    workflow body's import chain, where the runtime's deterministic sandbox
    refuses it.
    """
    return {
        "approvals": [
            {
                "tool_call_id": c.tool_call_id,
                "tool_name": c.tool_name,
                "args": c.args_as_dict()}
            for c in requests.approvals
        ],
        "calls": [c.tool_call_id for c in requests.calls]}


@wf.workflow
async def gated_turn(
    *,
    token: str,
    prompt: str,
    model_id: str,
    root_dir: str,
    active_agent: str | None = None,
    active_agent_description: str | None = None,
) -> dict[str, Any]:
    """One chat turn whose writes wait for the user, durably.

    :param token: Namespace for this turn's hook — also the answer endpoint's key.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: The turn's outcome, readable from a fresh ``Run`` handle.
    """
    stream = workflow.get_writable(type=Frame)
    history: list[dict[str, Any]] = []
    deferred: Any = None
    passes = 0

    while True:
        outcome = await agent_step(
            writable=stream,
            prompt=prompt,
            model_id=model_id,
            root_dir=root_dir,
            history=history,
            deferred=deferred,
            active_agent=active_agent,
            active_agent_description=active_agent_description,
        )
        passes += 1
        history = outcome["history"]
        pending = outcome["pending"]
        if not pending:
            break

        # The body waits. A hook is the one place a wait survives the process,
        # which is what makes this gate durable rather than a future that dies
        # with the server.
        decision = await WriteGate.wait(token=f"{token}-write")
        granted = [
            {"tool_call_id": p["tool_call_id"], "approved": _approved(decision)}
            for p in pending
        ]
        deferred = _rebuild_results(granted)

    await close_frames(writable=stream)
    return {"passes": passes, "frames": outcome["frames"]}


def _approved(decision: WriteGate) -> bool:
    """Whether the user allowed the write. A stop or a missing answer denies."""
    return decision.decision == "approved"


def _rebuild_results(
    outcome: dict[str, Any], granted: list[dict[str, Any]]
) -> Any:
    """The decisions as ``DeferredToolResults`` for the resumed pass."""
    from pydantic_ai.tools import DeferredToolResults, ToolApproved, ToolDenied

    approvals = {
        g["tool_call_id"]: (ToolApproved() if g["approved"] else ToolDenied())
        for g in granted
    }
    return DeferredToolResults(approvals=approvals)


@wf.step
async def close_frames(*, writable: workflow.WorkflowWritable[Frame]) -> None:
    """Close the frame stream so readers know the turn is over."""
    await writable.close()
