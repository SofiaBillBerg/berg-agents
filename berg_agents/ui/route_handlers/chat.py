# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Chat streaming endpoint.

Extracted from ``create_router`` — one concern per module. The streaming
chat endpoint uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter`
for native Vercel AI SSE protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cached_property
import logging
from typing import Any

from berg_agents.agents.chat_agent import build_chat_agent
from berg_agents.config.settings import get_settings
from berg_agents.core.harness import Harness
from berg_agents.core.turn import record_turn_outcome
from berg_agents.ui.projects import resolve_project
from berg_agents.ui.run_registry import (
    LiveRun,
    SessionRuntime,
    StaleApprovalError,
)
from berg_agents.ui.sessions import SessionManager
from berg_agents.ui.transcripts import append_new_messages, ensure_transcript
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.tools import ToolApproved, ToolDenied
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import (
    ToolApprovalResponded,
    ToolApprovalRespondedPart,
)
from pydantic_ai.usage import UsageLimits

logger = logging.getLogger(__name__)

_MAX_EMPTY_STREAM_ATTEMPTS = 2

#: Usage limits for a chat run - no model-request cap.
#:
#: pydantic-ai defaults to ``UsageLimits(request_limit=50)``, capping the
#: model responses committed by a single run. A chat session is not a single
#: run: it is a long-running, resumable conversation, and
#: :mod:`berg_agents.ui.session_store` carries the conversation's accumulated
#: usage back into every turn. The default therefore bounds the whole
#: *conversation* at 50 model requests.
#:
#: Runaway protection is a HITL request through the approval batch, not a
#: hard error mid-turn, so the request cap is disabled here.
_CHAT_USAGE_LIMITS = UsageLimits(request_limit=None)


class BergVercelAIAdapter(VercelAIAdapter):
    """Vercel AI adapter with per-step HITL approval support.

    The stock adapter maps each answered approval to a bare ``True`` or
    ``False``. That discards the arguments the user edited in the UI
    before approving. This subclass instead maps an *approved* call to
    :class:`pydantic_ai.ToolApproved` carrying the part's ``input`` as
    ``override_args``: the part's input is the original call's args
    when untouched (a no-op override) and the user's edited args when
    they revised them, so edits reach the actual tool execution.

    Denials keep the stock behavior (``False``, or
    ``ToolDenied(message=...)`` when the user gave a reason).
    """

    @cached_property
    def deferred_tool_results(self) -> DeferredToolResults | None:
        """Build the resume payload from the answered approval parts.

        :return: Deferred results for every answered approval in the
            incoming request, or ``None`` when it carries no answers.
        """
        approvals: dict[str, ToolApproved | ToolDenied | bool] = {}
        for msg in self.run_input.messages:
            if msg.role != "assistant":
                continue
            for part in msg.parts:
                if not isinstance(part, ToolApprovalRespondedPart):
                    continue
                approval = part.approval
                if not isinstance(approval, ToolApprovalResponded):
                    continue
                if approval.approved:
                    # The part's input carries the (possibly user-edited)
                    # args; unchanged input is a no-op override.
                    approvals[part.tool_call_id] = (
                        ToolApproved(override_args=part.input)
                        if part.input is not None
                        else True
                    )
                elif approval.reason:
                    approvals[part.tool_call_id] = ToolDenied(
                        message=approval.reason
                    )
                else:
                    approvals[part.tool_call_id] = False
        return DeferredToolResults(approvals=approvals) if approvals else None


async def _cap_tool_results(events: Any) -> Any:
    """Cap every tool result before it is sent back to the model.

    Tool results accumulate in the conversation and are re-sent with each
    later request, so one enormous result does not just bloat that turn -
    it bloats every turn after it, until the provider rejects the request
    outright (observed: a looping tool returned 65 MB, and the provider's
    50 MB limit turned every retry into an HTTP 413 that ended the
    session).

    This sits on the event stream rather than in any one tool because the
    cap must hold for every tool, including plugin tools written later
    that know nothing about it. Truncation is marked in the text so the
    model can tell its view is partial and narrow the call, rather than
    reasoning from a silently gutted result.

    :param events: Async iterator of pydantic-ai native events.
    :return: The same events, with oversized tool-return parts trimmed.
    """
    from berg_agents.core.loop import MAX_TOOL_RESULT_CHARS

    async for event in events:
        part = getattr(event, "part", None)
        content = getattr(part, "content", None)
        if (
            part is not None
            and isinstance(content, str)
            and len(content) > MAX_TOOL_RESULT_CHARS
        ):
            name = str(getattr(part, "tool_name", "") or "tool")
            dropped = len(content) - MAX_TOOL_RESULT_CHARS
            logger.warning(
                "tool %s returned %d chars; capped to %d for the model",
                name,
                len(content),
                MAX_TOOL_RESULT_CHARS,
            )
            part.content = _truncated_result(name, content, dropped)
        yield event


def _truncated_result(name: str, content: str, dropped: int) -> str:
    """Render a capped tool result with an explicit truncation notice.

    :param name: Tool name, named in the notice.
    :param content: The full result text.
    :param dropped: Characters that did not fit.
    :return: The head of the result plus a notice telling the model what
        was cut and how to get the rest.
    """
    from berg_agents.core.loop import MAX_TOOL_RESULT_CHARS

    return (
        content[:MAX_TOOL_RESULT_CHARS]
        + f"\n\n[... TRUNCATED by berg-agents: {dropped} more characters "
        f"were dropped from this {name} result. Only the first "
        f"{MAX_TOOL_RESULT_CHARS} characters are shown. Re-run the call "
        "with a narrower scope if you need the rest.]"
    )


async def encode_run_stream(
    events: Any, *, on_cancel: Callable[[Any], Awaitable[None]] | None = None
) -> Any:
    """Encode a run's native event stream as Vercel AI SSE frames.

    The run owns the graph (see :mod:`berg_agents.ui.run_registry`); this
    function owns the wire format. It delegates to the adapter's own
    ``run_stream``, so message identities, step boundaries, approval parts and
    the cancellation/error close-out stay in one place. The bytes are what
    ``VercelAIAdapter.dispatch_request`` produced when the response *was* the
    run.

    The encoder spans the whole turn, not one node: the protocol's ``start``
    and ``finish`` frames bracket a turn, so a per-node encoder would open the
    message repeatedly.

    :param events: Async iterator of pydantic-ai native events.
    :param on_cancel: Notified once when the run ends in a first-party
        cancellation, so the run can record why it stopped.
    :return: Async iterator of ``data: {...}`` frames.
    """
    from pydantic_ai.ui.vercel_ai import VercelAIEventStream

    async def _on_cancel(cancelled: Any) -> Any:
        """Forward the first-party cancellation to the run, then yield nothing."""
        if on_cancel is not None:
            await on_cancel(cancelled)
        return
        yield  # pragma: no cover - makes this an async generator

    stream = VercelAIEventStream(sdk_version=6)
    async for frame in stream.encode_stream(
        stream.transform_stream(_cap_tool_results(events), on_cancel=_on_cancel)
    ):
        yield frame


async def _persist_turn(
    request: Request,
    sessions: SessionManager,
    *,
    session_id: str | None,
    model_id: str,
    run: Any,
    outcome: Any,
) -> None:
    """Save a finished run: transcript, JSONL log, conversation, guard.

    The run's own messages are the record of the turn - they survive a Stop
    (first-party cancellation keeps completed work), so a stopped or paused
    turn is saved rather than lost.

    :param request: The originating request (for the harness).
    :param sessions: Session store (root dir).
    :param session_id: Session the turn belongs to.
    :param model_id: Model used, for the outcome record.
    :param run: The finished ``LiveRun``.
    :param outcome: How it ended.
    """
    _record_chat_outcome(
        request,
        sessions,
        success=outcome.kind == "completed",
        model_id=model_id,
    )
    # The run has yielded control back to the human: the turn finished, or it
    # paused on a deferred approval (the runaway guard's hard stop, or any
    # requires_approval tool), or it was stopped. All end unattended work, so
    # the runaway guard's count restarts either way.
    _reset_runaway_guard(session_id)

    agent_run = run.agent_run
    if not session_id or agent_run is None:
        return
    try:
        from berg_agents.ui import session_store
        from pydantic_ai import ConversationTypeAdapter

        root = sessions._harness_root_dir()
        store = session_store.get_store(root)
        # A steer the run ended before reading is still the human's message:
        # it joins the turn's record as a user prompt, so the transcript
        # never drops something Sofia actually typed.
        unread = [
            ModelRequest(parts=[UserPromptPart(content=text)])
            for text in run.unread_steering
        ]
        await session_store.record_turn(
            store, session_id, [*agent_run.all_messages(), *unread]
        )
        # The durable JSONL log takes only what THIS run produced.
        # `all_messages()` re-sends the whole conversation every turn (the
        # model needs the history), so appending it grew the transcript
        # quadratically and stored each turn's copy of every earlier turn.
        # `new_messages()` is exactly the turn's own messages - the input
        # history and older runs are excluded - which is what an append-only
        # log wants. `append_new_messages` still dedupes, because the memory
        # snapshot legitimately reappears each turn.
        append_new_messages(
            session_id,
            resolve_project(root),
            [*agent_run.new_messages(), *unread],
        )
        conversation_obj = session_store.load_conversation(session_id)
        if conversation_obj is not None:
            payload = ConversationTypeAdapter.dump_json(conversation_obj)
            await asyncio.to_thread(
                session_store.save_conversation,
                session_id,
                payload.decode("utf-8"),
            )
    except Exception as exc:
        logger.warning("Session save skipped: %s", exc)


def _record_chat_outcome(
    request: Request, sessions: SessionManager, *, success: bool, model_id: str
) -> None:
    """Feed one chat turn into the shared outcome store.

    Chat is the main surface, so its turns must reach the same outcome store
    as harness tasks - otherwise router stats never fires. Failure-isolated.

    :param request: The originating request (for the harness).
    :param sessions: Session store (for the fallback active model).
    :param success: Whether the turn completed.
    :param model_id: Model used.
    """
    try:
        harness = request.app.state.harness
        if harness is None:
            return
        record_turn_outcome(
            harness,
            task_type="chat",
            complexity="standard",
            description="chat turn",
            inference_attempted=True,
            model_used=model_id or sessions.active_model or "unknown",
            success=success,
        )
    except Exception as exc:
        logger.warning("router stats record skipped: %s", exc)


def _reset_runaway_guard(session_id: str | None) -> None:
    """Restart the runaway guard's count when the agent yields control.

    The guard counts tool calls since the human last had a say. It resets when
    the agent YIELDS control - the turn finished, the run paused for approval,
    or the user stopped it. It does not reset because the user typed: a message
    sent while the agent keeps working is steering, not an intervention.

    :param session_id: Session whose count restarts.
    """
    if not session_id:
        return
    try:
        from berg_agents.ui import session_store

        session_store.reset_guard_progress(session_id)
    except Exception as exc:
        logger.warning("runaway guard reset skipped: %s", exc)


def _steer_live_run(
    registry: Any, session_id: str | None, body: bytes
) -> Any | None:
    """Queue this request's text on a live run, if there is one.

    A message typed while the agent works is **steering**, not an
    interruption: it joins the run and reaches the model at its next request.
    Nothing in flight is aborted.

    A steer that cannot land (the run ended meanwhile) is not an error to the
    human: it returns ``None`` so the same request starts a fresh run instead,
    and the message is answered rather than swallowed.

    :param registry: The process-wide ``RunRegistry``.
    :param session_id: Session the request belongs to.
    :param body: Raw request body.
    :return: The live run to follow, or ``None`` when this request must start
        a run instead (no live run, no text to steer with, or a run that
        ended before the message could join it).
    """
    run = registry.live_run(session_id) if session_id else None
    if run is None:
        return None
    text = _latest_user_text(body)
    if not text:
        return None
    enqueue_id = run.steer(text)
    return run if enqueue_id else None


async def _start_run(
    registry: Any,
    *,
    session_id: str | None,
    body: bytes,
    agent: Any,
    conversation: Any,
    on_finish: Callable[[Any, Any], Awaitable[None]],
) -> Any:
    """Start the session's next run and return it.

    The run is created under the session's lock so two messages can never
    start two runs, and it starts in its own task - the HTTP response that
    follows is only a reader.

    :param registry: The process-wide ``RunRegistry``.
    :param session_id: Session the run belongs to.
    :param body: Raw request body (its approvals decide resume vs fresh).
    :param agent: The session's agent.
    :param conversation: The session's ``Conversation`` (usage + id carry).
    :param on_finish: Persistence hook, called once when the run ends.
    :return: The started ``LiveRun``, or the live run this text was steered
        into when one appeared while this request was resolving its session.
    """
    async with registry.lock(session_id or ""):
        # Re-check under the lock: a run may have started while this request
        # was resolving its session. Text then joins that run (steering).
        run = registry.live_run(session_id) if session_id else None
        if run is not None:
            text = _latest_user_text(body)
            if text and run.steer(text):
                return run

        if run is not None and _approvals_from_body(body) is not None:
            # An approval for a run that already ended: the decision is for
            # nothing, so answer it here instead of failing the request. The
            # client's own expired-approval handling keeps the card honest.
            raise StaleApprovalError(
                "the run this approval belongs to has ended"
            )

        runtime = registry.get(session_id) if session_id else None
        generation = (runtime.generation if runtime else 0) + 1
        if runtime is not None:
            runtime.generation = generation

        # An approval resume carries no user text: the model continues from
        # the deferred batch. Anything else is a fresh turn with a prompt.
        approvals = _approvals_from_body(body)
        prompt = None if approvals is not None else _latest_user_content(body)

        # A resume continues from the client's own message list: that is where
        # the paused tool call lives (the run's history holds only what the
        # model already saw), and it is what the approval ids point into. A
        # fresh turn uses the session's conversation, so usage and the
        # conversation id carry across turns.
        start_args: dict[str, Any] = (
            {"message_history": _history_from_body(body)}
            if approvals is not None
            else {"conversation": conversation}
        )

        def _request() -> Any:
            """Create the graph run inside the run's own task."""
            return agent.iter(
                prompt,
                output_type=[str, DeferredToolRequests],
                usage_limits=_CHAT_USAGE_LIMITS,
                deferred_tool_results=approvals,
                **start_args,
            )

        live = LiveRun(
            agent=agent,
            request=_request,
            generation=generation,
            max_duration=get_settings().run_max_duration_minutes * 60,
            on_finish=on_finish,
        )
        if runtime is not None:
            runtime.run = live
        live.start()
        return live


def _run_status(registry: Any, session_id: str | None) -> dict[str, Any]:
    """Describe the session's current run, or ``None`` when it has none.

    :param registry: The process-wide ``RunRegistry``.
    :param session_id: Session to describe.
    :return: Run status dict, or ``{"live": False}`` when idle.
    """
    runtime = registry.get(session_id) if session_id else None
    if runtime is None or runtime.run is None:
        return {"live": False, "generation": 0, "steering": [], "outcome": None}
    return runtime.run.status()


def _follow_response(run: Any, session_id: str | None = None) -> Response:
    """Return the run's journal as an SSE response.

    The response is a *reader*. When the browser goes away the generator is
    closed and nothing else happens - the run keeps going, and a later
    request replays the journal from the start.

    :param run: The ``LiveRun`` to read.
    :param session_id: Session the run belongs to, echoed as a header. A
        client that sent no id had one minted for it, and this is how it
        learns which conversation it is now in - without it, Stop and
        follow would address nothing until a reload.
    :return: StreamingResponse in the Vercel AI SSE protocol.
    """
    from starlette.responses import StreamingResponse

    headers = {
        # SSE must not be buffered by a proxy: the browser sees chunks as the
        # run produces them, not after the run ends.
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "x-vercel-ai-ui-message-stream": "v1"}
    if session_id:
        headers["x-berg-session-id"] = session_id
    return StreamingResponse(
        run.subscribe(), media_type="text/event-stream", headers=headers
    )


def _latest_user_text(body: bytes) -> str:
    """Return the newest user text this request sends, or '' when it sends none."""
    content = _latest_user_content(body)
    if not content:
        return ""
    if isinstance(content, str):
        # A single-text message arrives as a plain string.
        return content
    return "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _latest_user_content(body: bytes) -> str | list[dict[str, Any]] | None:
    """Return the user message this request is *sending*, if any.

    A message typed while the agent works is **steering**, and the client
    sends its whole message list with it: the newest message in the list is
    then the assistant turn that is still growing, and the steering text sits
    one user message back. The message being sent is therefore the newest
    user message **not already answered by an assistant turn**: the last
    user message when the list ends on a user turn, otherwise the last user
    message that follows the last assistant turn.

    :param body: Raw request body (Vercel AI protocol).
    :return: Plain string for the usual single-text message, a list of
        content parts when the message carries more than text, or ``None``
        when the body sends no new user message (an approval-only resume, or
        a steer in a run whose model has not answered anything since).
    """
    try:
        import json

        data = json.loads(body)
    except Exception:
        return None
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        return None
    if isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
        # The list ends on the user's turn: that message is what is sent.
        newest = messages[-1]
    else:
        # The list ends on an assistant turn still in progress: the text
        # being sent is the newest user message before it - the last one
        # the assistant has not answered, i.e. a steering message.
        newest = None
        assistant_at = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if isinstance(messages[index], dict)
                and messages[index].get("role") == "assistant"
            ),
            None,
        )
        if assistant_at is not None:
            newest = next(
                (
                    message
                    for message in reversed(messages[:assistant_at])
                    if isinstance(message, dict)
                    and message.get("role") == "user"
                ),
                None,
            )
    if not isinstance(newest, dict):
        return None
    parts = newest.get("parts")
    if not isinstance(parts, list):
        return None
    texts = [
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ]
    return texts[0] if len(parts) == 1 and texts else parts


def _history_from_body(body: bytes) -> list[Any] | None:
    """Load the model history a resume continues from, out of the request body.

    The paused tool call lives in the client's message list - the model's own
    history only holds what it already saw - so a resume is built from the
    body, the same way the adapter's own dispatch built it.

    :param body: Raw request body (Vercel AI protocol).
    :return: The model messages, or ``None`` when the body cannot be read.
    """
    try:
        adapter = BergVercelAIAdapter.build_run_input(body)
        return BergVercelAIAdapter(agent=None, run_input=adapter).messages
    except Exception as exc:
        logger.warning("resume history skipped: %s", exc)
        return None


def _approvals_from_body(body: bytes) -> DeferredToolResults | None:
    """Build the resume payload from a request's answered approvals.

    Uses the adapter's own parsing so approval semantics (edited args,
    denial reasons) stay in one place. The agent is never run from here:
    only the answered parts are read.

    :param body: Raw request body (Vercel AI protocol).
    :return: Deferred results, or ``None`` when the body carries no answers.
    """
    try:
        adapter = BergVercelAIAdapter.build_run_input(body)
        answered = BergVercelAIAdapter(agent=None, run_input=adapter)
        return answered.deferred_tool_results
    except Exception as exc:
        logger.warning("approval parse skipped: %s", exc)
        return None


async def _track_chat_session(
    request: Request, sessions: SessionManager, model_id: str
) -> tuple[str | None, Any]:
    """Track the server-side session for a chat turn.

    Failure-isolated: sessions must never break chat, so any error
    logs and returns ``(None, None)``.
    """
    session_id: str | None = None
    conversation: Any = None
    try:
        from berg_agents.ui import session_store

        body = await request.json()
        raw_session = body.get("sessionId") if isinstance(body, dict) else None
        root_dir = sessions._harness_root_dir()
        store = session_store.get_store(root_dir)
        # Mint against the resolved project so a new id names it; an id the
        # client already holds (including a legacy bare uuid) passes through.
        session_id = session_store.coerce_session_id(
            raw_session, resolve_project(root_dir).id
        )
        await session_store.ensure_session(
            store,
            session_id,
            workspace=session_store.project_name(root_dir),
            subtitle=session_store.first_user_text(
                body.get("messages") if isinstance(body, dict) else None
            ),
            model=model_id or sessions.active_model,
        )
        session_store.set_active_session(root_dir, session_id)
        conversation = session_store.load_conversation(session_id)
        # Durable append-only transcript: create the project record and
        # the session header line (idempotent — created_at is never
        # rewritten, so it survives restarts and renames).
        ensure_transcript(
            session_id,
            resolve_project(root_dir),
            model=model_id or sessions.active_model,
        )
        # Refine the generated title with the intent once the first user
        # text is in hand: the session is created before any message
        # exists, so `#N · date` is all it can carry at that point. The
        # id never changes — a session resumed days later keeps it, and
        # a title the user renamed is left alone.
        raw_messages = body.get("messages") if isinstance(body, dict) else None
        await session_store.refine_session_title(
            store,
            session_id,
            session_store.first_user_text(raw_messages),
            session_store.project_name(root_dir),
        )
    except Exception as exc:
        logger.warning("Session tracking skipped: %s", exc, exc_info=True)
        session_id = None
        conversation = None
    return session_id, conversation


def _resolve_active_agent(
    harness: Harness, sessions: SessionManager
) -> tuple[str | None, str | None]:
    """Resolve the active agent + its description (None when stale/absent)."""
    active_agent = sessions.active_agent
    active_agent_description: str | None = None
    if active_agent:
        try:
            info = harness.get_agent(active_agent).get_info()
            active_agent_description = info.get("description")
        except KeyError:
            sessions.active_agent = None
            active_agent = None
    return active_agent, active_agent_description


def _chat_error_hint(text: str) -> str:
    """Human-readable hint for a failed chat request, or ''."""
    lowered = text.lower()
    if "system message" in lowered or "jinja" in lowered:
        return (
            " This model enforces strict chat-template rules "
            "(system-prompt placement) and rejected the request "
            "shape — try another model."
        )
    if "401" in lowered or "auth" in lowered:
        return " Check the provider API key for this model."
    return ""


def _track_context_usage(agent: Any, session_id: str | None) -> None:
    """Report the chat agent's context usage into the gauge holder.

    ``ReportContextUsage`` already emits ``ContextUsageEvent`` on every
    model request; without a subscriber nothing read it, so the user
    could not see the context filling or compaction arriving. This is
    that subscriber. Failure-isolated: the gauge must never break chat.

    :param agent: The chat agent (carries the capability's event bus).
    :param session_id: Session the readings are attributed to.
    """
    if not session_id:
        return
    try:
        from berg_agents.ui import context_usage
        from pydantic_ai_harness.compaction import ContextUsageEvent

        def _on_usage(ctx: Any, event: Any) -> None:
            # pydantic-ai delivers more than ContextUsageEvent to a
            # handler registered by type (PartStartEvent and friends
            # arrive too), so filter on the fields we actually read
            # rather than trusting the subscription's type.
            if not hasattr(event, "used_tokens"):
                return
            context_usage.record(session_id, event)

        # NOTE: handler FIRST. `on_event(event_type, handler)` registers
        # the handler as an extra *event type* and silently fires never —
        # which is exactly what happened before this was caught.
        agent.on_event(_on_usage, ContextUsageEvent)
    except Exception as exc:
        logger.warning(f"Context usage gauge unavailable: {exc}")


def register_chat_routes(
    router: APIRouter, *, harness: Harness, sessions: SessionManager
) -> None:
    """Register the streaming chat endpoint.

    :param router: Router to attach endpoints to.
    :param harness: Shared harness (single instance per app).
    :param sessions: Session store (active provider/model + root dir).
    """

    def _session_agent(
        request: Request,
        *,
        session_id: str | None,
        model_id: str,
        plugin_tools: Any,
        disabled_mcp: Any,
        disabled_skills: Any,
        active_agent: str | None,
        active_agent_description: str | None,
    ) -> Any:
        """Return the session's agent, building it only when it must change.

        Resolving a model, loading skills, connecting MCP toolsets and reading
        Shared Context are the expensive parts of a turn, and none of them
        depend on the message. So they happen once per session and repeat only
        when the configuration they were built from actually changes.

        :param request: The running request (carries the run registry).
        :param session_id: Session the agent belongs to.
        :param model_id: Active provider/model id.
        :param plugin_tools: Plugin-contributed tools.
        :param disabled_mcp: MCP servers the user withheld this turn.
        :param disabled_skills: Skills the user withheld this turn.
        :param active_agent: Persona selected via ``/api/agents/active``.
        :param active_agent_description: That persona's description.
        :return: The session's live agent, reused across turns.
        """
        registry = request.app.state.run_registry
        fingerprint = (
            model_id,
            sessions._harness_root_dir(),
            tuple(getattr(t, "name", repr(t)) for t in plugin_tools),
            frozenset(disabled_mcp),
            frozenset(disabled_skills),
            active_agent,
            active_agent_description or "",
        )
        runtime = registry.get(session_id) if session_id else None
        if runtime is not None and runtime.fingerprint == fingerprint:
            return runtime.agent

        agent = build_chat_agent(
            model_id,
            root_dir=sessions._harness_root_dir(),
            plugin_tools=plugin_tools,
            disabled_mcp=disabled_mcp,
            disabled_skills=disabled_skills,
            active_agent=active_agent,
            active_agent_description=active_agent_description,
            # Scopes the plan store to this session so a plan written
            # in one turn is still there in the next.
            session_id=session_id,
        )
        _track_context_usage(agent, session_id)
        if session_id:
            registry.put(
                SessionRuntime(
                    session_id=session_id, agent=agent, fingerprint=fingerprint
                )
            )
        logger.info("chat agent built for %s", session_id or "(no session)")
        return agent

    @router.post("/api/chat/stream")
    async def chat_stream(request: Request) -> Response:
        """Agentic streaming chat - native Vercel AI protocol via pydantic_ai.

        The POST no longer *is* the run. It hands the message to the
        session's run - starting one when idle, steering a live one - and
        returns a subscription to that run: the same Vercel AI SSE protocol as
        before, read from a replayable journal the run owns. Closing the
        response stops nothing; stopping is ``POST /api/chat/stop``.

        Three request shapes share this one path:

        * a fresh user message (session idle) - starts a new run;
        * approval answers (the run paused on ``DeferredToolRequests``) -
          resumes the same conversation with that batch's decisions;
        * a mid-run message (run live) - **steering**: queued for the model's
          next request, never an interruption.

        Multi-step requests stay visible: the model plans first
        (``plan_task``), then implements (``implement_task``), so progress,
        steering points and approvals are streamed rather than hidden inside
        one opaque call.

        The agent, model, and system prompt all come from configuration
        (``.berg-agents/bergagents.jsonc`` and ``.berg-agents/profiles.yaml``) - never
        hardcoded. An optional ``?model=`` query param overrides the model.

        :param request: FastAPI request - VercelAIAdapter inspects the body
            and ``accept`` header to pick the protocol and parse messages.
        :return: StreamingResponse with SSE chunks in Vercel AI protocol.
        """
        from plugin_system import get_chat_plugin_state

        # Model override via query param (the body is consumed by the adapter).
        model_id = (
            request.query_params.get("model") or sessions.active_model or ""
        )

        # NOTE: Server-side session (any browser, any profile). The
        # frontend sends its session id in the body; the authoritative
        # transcript is saved on completion. All failure-isolated:
        # sessions must never break chat.
        session_id, conversation = await _track_chat_session(
            request, sessions, model_id
        )
        # NOTE: Plugin state is per-turn and failure-isolated: a broken
        # plugin dir only logs, chat still gets its agent. Disabled
        # plugins are withheld from tools, MCP toolsets, and skills.
        # Tools are resolved for THIS session, so a plugin's scoped
        # store (e.g. shared-todo's todo_path) belongs to this
        # conversation and not to every session under the project.
        (
            plugin_tools,
            disabled_mcp,
            disabled_skills,
        ) = await get_chat_plugin_state(
            root_dir=sessions._harness_root_dir(), session_id=session_id
        )

        # Active agent selection (set via /api/agents/active). Routes the
        # next message to that agent: build_chat_agent adopts its persona.
        active_agent, active_agent_description = _resolve_active_agent(
            harness, sessions
        )

        agent = _session_agent(
            request,
            session_id=session_id,
            model_id=model_id,
            plugin_tools=plugin_tools,
            disabled_mcp=disabled_mcp,
            disabled_skills=disabled_skills,
            active_agent=active_agent,
            active_agent_description=active_agent_description,
        )

        # sdk_version=6 enables tool-approval streaming (human-in-the-loop).
        # BergVercelAIAdapter.dispatch_request handles all SSE encoding
        # and protocol transformation natively - no manual event loops
        # needed. output_type adds DeferredToolRequests: tools flagged
        # requires_approval (bash, edit_file, write_file,
        # implement_task) pause the run instead of executing, the
        # adapter streams an approval request, and the frontend answers
        # it with addToolApprovalResponse - which re-POSTs here
        # carrying the approval. The adapter extracts approvals from
        # the incoming messages and resumes the same run; approved
        # calls may carry user-edited args (see the subclass). (The
        # adapter only adds DeferredToolRequests itself when it
        # contributes a toolset, which we don't use - hence declaring
        # it explicitly.)

        async def _on_run_finish(run: Any, outcome: Any) -> None:
            """Persist the turn, then hand control back to the human.

            Called by the run itself, so persistence never depends on a
            browser still being connected.

            :param run: The finished ``LiveRun``.
            :param outcome: How it ended.
            """
            logger.info(
                "chat run finished: %s (%s)", outcome.kind, outcome.detail
            )
            await _persist_turn(
                request,
                sessions,
                session_id=session_id,
                model_id=model_id,
                run=run,
                outcome=outcome,
            )

        # -- request meaning -------------------------------------------------
        body = await request.body()
        registry = request.app.state.run_registry

        run = _steer_live_run(registry, session_id, body)
        if run is not None:
            return _follow_response(run, session_id)

        try:
            live = await _start_run(
                registry,
                session_id=session_id,
                body=body,
                agent=agent,
                conversation=conversation,
                on_finish=_on_run_finish,
            )
        except StaleApprovalError as exc:
            # Nothing is running to answer: say so plainly instead of failing
            # the request, so the client can expire the card and move on.
            logger.info("approval answered after its run ended: %s", exc)
            return JSONResponse(
                status_code=409, content={"detail": str(exc), "stale": True}
            )
        return _follow_response(live, session_id)

    @router.get("/api/chat/stream")
    async def chat_follow(request: Request) -> Response:
        """Follow the session's live run without sending anything.

        This is how a reload, a tab switch or a second browser rejoins a run
        that is still going: the run replays its journal from the start, so
        the client rebuilds the same turn instead of joining mid-message.

        A finished run is not followed - the transcript is the record then,
        and the client reloads it from ``/api/sessions/{id}``.

        "Nothing to follow" is answered 204, not an error. A client learns a
        run is live from the status endpoint, and the run can end in the
        instant before it subscribes; that race is normal, and 204 is the
        protocol's way of saying so (the client's reconnect returns ``null``
        and simply stops). An error status would surface a failure to the
        human for a turn that actually finished correctly.

        :param request: FastAPI request (``?session=`` names the session).
        :return: SSE stream, or 204 when there is no live run to follow.
        """
        from fastapi import Response as FastAPIResponse

        session_id = request.query_params.get("session")
        run = (
            request.app.state.run_registry.live_run(session_id)
            if session_id
            else None
        )
        if run is None:
            return FastAPIResponse(status_code=204)
        return _follow_response(run, session_id)

    @router.post("/api/chat/stop")
    async def chat_stop(request: Request) -> dict[str, Any]:
        """Stop the session's live run - the explicit interruption.

        This is the only thing that cancels a run. Closing a stream, reloading
        a page or switching tabs does not: those are readers leaving. What the
        run already completed stays in history and is saved, and the human
        gets control back (the runaway guard restarts).

        :param request: FastAPI request (``?session=`` names the session).
        :return: Whether a run was stopped.
        """
        session_id = request.query_params.get("session")
        run = (
            request.app.state.run_registry.live_run(session_id)
            if session_id
            else None
        )
        if run is None:
            return {"stopped": False}
        await run.cancel("stopped by user")
        return {"stopped": True}

    @router.get("/api/chat/status")
    async def chat_status(request: Request) -> dict[str, Any]:
        """Report the session's run state, including unread steering.

        The browser uses this on mount so the steering strip means the same
        thing after a reload: "the agent has not read this yet".

        :param request: FastAPI request (``?session=`` names the session).
        :return: Run status.
        """
        return _run_status(
            request.app.state.run_registry, request.query_params.get("session")
        )
