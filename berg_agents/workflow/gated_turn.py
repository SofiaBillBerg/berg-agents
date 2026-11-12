"""A gated write on the durable host — phase 1c, slice b.

**The shape this implements, and why it is not a waiting hook:** a deferred
write means the run has ENDED. pydantic-ai's UI adapter makes that explicit —
``dispatch_request`` passes ``deferred_tool_results=`` into the agent run, and
``deferred_tool_results`` is built from the approval responses carried in the
POST body (``pydantic_ai/ui/vercel_ai/_adapter.py:314``, ``:356``). The
``ToolApprovalRequestedPart`` the frontend renders from is emitted at ``:1073``,
in the message-reconstruction path, whose own comment says it exists so the
frontend can draw buttons on *reload*. So there is no in-process wait to hold —
the durable gate is: the run ends parked, the user decides, and the *same run*
is re-driven with the decision plus its own history.

That shape is also exactly what the durable host wants, and better than a hook:
each pass is a durable run, so the decision survives because the run record
does — no process-local future, no hook to resolve.

Two passes, one workflow:

    outcome = await run_pass(...)          # ends parked, cards on the stream
    if outcome.pending:
        decision = <stored by the approval endpoint>
        outcome = await run_pass(..., deferred=decision, history=outcome.history)

The approval endpoint stores the decision keyed by the run id, and re-drives
*that run* — so Sofia's click answers the same turn, not a new one.
"""

from __future__ import annotations

from typing import Any

from berg_agents.workflow.registry import Frame, wf
from vercel import workflow


# A step must be declared async even when its body has nothing to await:
# the runtime resolves it by signature, not by whether it yields.
def _decision_for(answer: dict[str, Any]) -> Any:
    """One approval decision, in the shape the run expects.

    An approval that carries a **steer instruction** is delivered as a denial
    *with that instruction as its message*, not as a silent approval. The
    difference matters: approving leaves the call to execute with the arguments
    the model already committed, and a local model will keep them — observed
    twice. A denial hands the model a message and makes it re-plan, so the
    steer actually changes what happens rather than merely being visible.

    :param answer: ``{"approved": bool, "reason": str | None, "steer": str |
        None}``, as the approval endpoint stored it.
    :return: ``ToolApproved`` or ``ToolDenied``.
    """
    from pydantic_ai.tools import ToolApproved, ToolDenied

    steer = str(answer.get("steer") or "").strip()
    if steer:
        return ToolDenied(
            message=(
                "The user changed the plan before this call ran. "
                f"{steer} Re-plan and call the tools again, using the new "
                "instruction instead of the arguments you had chosen."
            )
        )
    if answer.get("approved"):
        return ToolApproved()
    return ToolDenied(
        message=answer.get("reason") or "The user rejected this call."
    )


@wf.step
async def take_steers(*, key: str) -> list[str]:  # ruff: ignore[unused-async]
    """Read and clear the steers waiting for this turn.

    A step, because a workflow body may not touch the filesystem — the runtime
    refuses ``io.open`` there, and a steer store is a file. Clearing on read is
    deliberate: the text is carried into this pass, and a later pass must not
    see it twice.

    :param key: The turn's token, which is what identifies the conversation a
        steer is addressed to across the runs that make up one turn.
    :return: The steer texts, oldest first.
    """
    from berg_agents.workflow.steering import clear_steers, read_steers

    texts = read_steers(key)
    if texts:
        clear_steers(key)
    return texts


@wf.step(cancellable=True)
async def run_pass(
    *,
    writable: workflow.WorkflowWritable[Frame],
    prompt: str,
    model_id: str,
    root_dir: str,
    history: list[dict[str, Any]],
    decisions: dict[str, Any] | None,
    steers: list[str] | None,
    active_agent: str | None,
    active_agent_description: str | None,
) -> dict[str, Any]:
    """One pass of the turn, ending either complete or parked at the gate.

    No ``HandleDeferredToolCalls`` capability is registered on purpose: with
    one, a gated call would be answered inside the run and the run could never
    end parked. Without one the run ends on ``DeferredToolRequests``, which is
    what this pass reports.

    :param writable: This turn's durable frame stream.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param history: The turn so far, for a resumed pass.
    :param decisions: The user's decision per call id, or ``None`` on the
        first pass. Plain data, decoded into ``DeferredToolResults`` here.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: The turn's history, whatever is pending at the gate, and the frame
        count this pass produced.
    """
    from berg_agents.agents.chat_agent import build_chat_agent
    from berg_agents.agents.deps import AgentDeps
    from berg_agents.ui.route_handlers.chat import encode_run_stream
    from berg_agents.ui.run_registry import (
        _is_end,
        _node_emits_events,
        _node_events,
        _run_result_event,
    )
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    agent = build_chat_agent(
        model_id,
        root_dir=root_dir,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )
    kwargs: dict[str, Any] = {
        "deps": AgentDeps(workspace_root=root_dir),
        # A gated tool ends the run parked instead of executing.
        "output_type": [str, _deferred_requests()]}
    if history:
        kwargs["message_history"] = ModelMessagesTypeAdapter.validate_python(
            history
        )
    # A steer that arrived while the run was parked is history, not injection:
    # the SDK's own rule for `enqueue` is that "at a deferred-tool pause the
    # content is added to the history instead". So it is appended as a user
    # turn and the model gets it on this pass.
    if steers:
        joined = "\n\n".join(steers)
        kwargs["message_history"] = [
            *(kwargs.get("message_history") or []),
            _user_turn(joined)]

    if decisions:
        # Rebuilt here, inside the step: a DeferredToolResults cannot be
        # serialised across the boundary, so only plain decisions travel.
        from pydantic_ai.tools import DeferredToolResults

        kwargs["deferred_tool_results"] = DeferredToolResults(
            approvals={
                call_id: _decision_for(answer)
                for call_id, answer in decisions.items()
            }
        )

    seen: dict[str, Any] = {"result": None, "messages": []}

    async def _events() -> Any:
        """This pass's native events in graph order, ending with its result.

        One iterator for the encoder, because its start/finish frames bracket a
        whole pass — feeding it per event duplicates the wire. It also records
        the outcome it saw, so the pass is walked once and not twice.
        """
        async with agent.iter(prompt, **kwargs) as run:
            node = run.next_node
            while not _is_end(node):
                # Only model-call and tool nodes emit protocol events.
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

    from pydantic_ai.messages import DeferredToolRequests

    # `AgentRun.run.result` is an `AgentRunResult` WRAPPER; the deferred batch is
    # its ``output``. Testing the wrapper directly never matched, which is why
    # this pass reported ``pending: []`` while the wire carried the approval
    # card — the gate held, but the body could not see what it held.
    result = seen["result"]
    deferred = getattr(result, "output", result)
    pending: list[dict[str, Any]] = []
    if isinstance(deferred, DeferredToolRequests):
        for call in deferred.approvals:
            pending.append({
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args_as_dict()})

    return {
        "history": _dump_messages(seen["messages"]),
        "pending": pending,
        "frames": frames}


def _user_turn(text: str) -> Any:
    """One user message, in the shape the run's history expects."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return ModelRequest(parts=[UserPromptPart(content=text)])


def _deferred_requests() -> Any:
    """``DeferredToolRequests`` without naming it at module level.

    Naming it at module level would pull pydantic_ai into the workflow body's
    import chain, and the runtime re-imports that chain inside a deterministic
    sandbox that refuses what pydantic_ai imports.
    """
    from pydantic_ai.messages import DeferredToolRequests

    return DeferredToolRequests


def _dump_messages(messages: Any) -> list[dict[str, Any]]:
    """A pass's messages as plain dicts, so the boundary can carry them."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    if not messages:
        return []
    return list(ModelMessagesTypeAdapter.dump_python(messages, mode="json"))


@wf.workflow
async def gated_turn(
    *,
    token: str,
    prompt: str,
    model_id: str,
    root_dir: str,
    active_agent: str | None = None,
    active_agent_description: str | None = None,
    _decisions: dict[str, Any] | None = None,
    _history: list[Any] | None = None,
    _steer_key: str | None = None,
) -> dict[str, Any]:
    """One chat turn whose writes end parked until the user decides.

    The decision does not arrive on a hook: this workflow ends parked, the
    approval endpoint stores the decision against the run id, and the endpoint
    re-drives *this run* with it. So the body only ever runs one pass — the
    resumed pass is a fresh run of the same workflow, started by the endpoint
    with the decision and this run's history.

    :param token: Namespace for this turn's stream; the approval route is
        keyed on the run id, which is durable.
    :param prompt: The user's message.
    :param model_id: Active provider/model id.
    :param root_dir: Workspace root the agent's tools bind to.
    :param active_agent: Persona selected via ``/api/agents/active``.
    :param active_agent_description: That persona's description.
    :return: The turn's outcome, readable from a fresh ``Run`` handle.
    """
    stream = workflow.get_writable(type=Frame)
    # Steers are read in a STEP, never in the body: a workflow body re-runs on
    # every replay and the runtime refuses file access there (`io.open`), so
    # the read has to be a step's work like every other side effect.
    # Taken here so a steer is delivered exactly once, by whichever pass
    # reaches it first — the approval endpoint reads the same store when it
    # resumes a parked run, so this pass sees only what arrived afterwards.
    pending_steers = await take_steers(key=_steer_key or token)
    outcome = await run_pass(
        writable=stream,
        prompt=prompt,
        model_id=model_id,
        root_dir=root_dir,
        # A resumed run carries the parked turn's history and the decision;
        # the first run starts empty. Both arrive as plain values so the
        # workflow boundary can cross them.
        history=_history or [],
        decisions=_decisions,
        steers=pending_steers,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )
    await close_frames(writable=stream)
    return outcome


@wf.step
async def close_frames(*, writable: workflow.WorkflowWritable[Frame]) -> None:
    """Close the frame stream so readers know the pass is over."""
    await writable.close()
