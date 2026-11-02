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
from functools import cached_property
import logging
from typing import Any, Literal

from berg_agents.agents.chat_agent import build_chat_agent
from berg_agents.core.harness import Harness
from berg_agents.core.turn import record_turn_outcome
from berg_agents.ui.projects import resolve_project
from berg_agents.ui.sessions import SessionManager
from berg_agents.ui.transcripts import append_new_messages, ensure_transcript
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.exceptions import UnexpectedModelBehavior
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


async def stream_node_chunks(stream: Any, node: Any, ctx: Any) -> Any:
    """Encode one agent-graph node's events as Vercel AI SSE chunks.

    The run owns the graph (see :mod:`berg_agents.ui.run_registry`); this
    function owns the wire format. It reuses the adapter's own event stream,
    which keeps message identities, step boundaries and approval parts in one
    place instead of reimplemented per node - the bytes stay identical to what
    ``VercelAIAdapter.dispatch_request`` produced when the response *was* the
    run.

    The stream is created once per RUN, not per node: the protocol's ``start``
    and ``finish`` frames bracket a whole turn, so a fresh encoder per node
    would emit several starts into one message.

    :param stream: The run's ``VercelAIEventStream`` (turn-long).
    :param node: A ``ModelRequestNode`` or ``CallToolsNode`` to stream.
    :param ctx: The run's graph context (``agent_run.ctx``).
    :return: Async iterator of encoded ``data: {...}`` frames.
    """
    if type(node).__name__ not in {"ModelRequestNode", "CallToolsNode"}:
        # Pure graph steps (user prompt, output validation) emit no protocol
        # events; opening their stream would only produce empty steps.
        return
    # transform_stream owns the node's event lifecycle: it turns the response
    # on at the first part and back off at a tool call, so a multi-step turn
    # reads like the single stream it replaces.
    async with node.stream(ctx) as node_stream:
        async for chunk in stream.transform_stream(node_stream):
            yield stream.encode_event(chunk)


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
        session_id = session_store.coerce_session_id(raw_session)
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

    @router.post("/api/chat/stream")
    async def chat_stream(request: Request) -> Response:
        """Agentic streaming chat - native Vercel AI protocol via pydantic_ai.

        Uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter` to handle all
        event transformation: frontend messages → agent run input, agent
        events → Vercel AI SSE chunks (text deltas, tool calls, tool results,
        HITL approval requests).

        Simple messages like "hello" get a direct LLM reply - no tool calls.
        Multi-step requests are handled through visible delegation:
        the model plans first (``plan_task``), then implements
        (``implement_task``) - each stage streams its own result into
        the transcript, so progress, steering points, and approvals
        stay visible instead of vanishing inside one opaque call.

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
        (
            plugin_tools,
            disabled_mcp,
            disabled_skills,
        ) = await get_chat_plugin_state()

        # Active agent selection (set via /api/agents/active). Routes the
        # next message to that agent: build_chat_agent adopts its persona.
        active_agent, active_agent_description = _resolve_active_agent(
            harness, sessions
        )

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

        # Learning: chat is the main surface, so its turns feed the same
        # outcome store as harness tasks - otherwise router
        # stats never fires.
        def _record_chat_outcome(success: bool) -> None:
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
                logger.warning(f"router stats record skipped: {exc}")

        def _log_run_cancelled(run_cancelled: object) -> None:
            # Fired when a client stop/disconnect cancels the run, so
            # the "Stop" button is observable server-side. A Stop is the
            # agent yielding control, so the runaway guard's count restarts.
            logger.info(f"chat run canceled: {run_cancelled}")
            _reset_runaway_guard()

        def _reset_runaway_guard() -> None:
            # The guard counts tool calls since the human last had a say.
            # It resets when the agent YIELDS control - the turn finished,
            # the run paused for approval, or the user stopped it. It does
            # not reset because the user typed: a message sent while the
            # agent keeps working is steering, not an intervention.
            if not session_id:
                return
            from berg_agents.ui import session_store

            session_store.reset_guard_progress(session_id)

        async def _save_turn(result: Any) -> None:
            # on_complete receives the AgentRunResult: persist both the
            # display transcript (any browser can resume it) and the
            # Conversation (usage + id carry into the next turn).
            _record_chat_outcome(success=True)
            if not session_id:
                return
            try:
                from berg_agents.ui import session_store
                from pydantic_ai import ConversationTypeAdapter

                root = sessions._harness_root_dir()
                store = session_store.get_store(root)
                messages = result.all_messages()
                await session_store.record_turn(store, session_id, messages)
                # The durable JSONL log takes only what THIS run produced.
                # `all_messages()` re-sends the whole conversation every
                # turn (the model needs the history), so appending it grew
                # the transcript quadratically and stored each turn's
                # copy of every earlier turn. `new_messages()` is exactly
                # the turn's own messages — the input history and older
                # runs are excluded — which is what an append-only log
                # wants. `append_new_messages` still dedupes, because the
                # memory snapshot legitimately reappears each turn.
                append_new_messages(
                    session_id, resolve_project(root), result.new_messages()
                )
                conversation_obj = getattr(result, "conversation", None)
                if conversation_obj is not None:
                    payload = ConversationTypeAdapter.dump_json(
                        conversation_obj
                    )
                    await asyncio.to_thread(
                        session_store.save_conversation,
                        session_id,
                        payload.decode("utf-8"),
                    )
                # The run has yielded control back to the human: either the
                # turn finished, or it paused on a deferred approval (the
                # runaway guard's hard stop, or any requires_approval tool).
                # Both end this stretch of unattended work.
                _reset_runaway_guard()
            except Exception as exc:
                logger.warning(f"Session save skipped: {exc}")

        # Proxy hiccups (observed via omniroute) can return an
        # entirely empty SSE stream; pydantic-ai surfaces that as
        # UnexpectedModelBehavior("... ended without content ...").
        # The failed step produced no assistant turn and executed
        # nothing, so re-sending the same request is safe: the
        # body is cached by Starlette and the retry simply
        # regenerates the missing turn instead of failing the chat.
        try:
            return await _dispatch_chat_with_retry(
                request,
                agent=agent,
                sdk_version=6,
                output_type=[str, DeferredToolRequests],
                session_id=session_id,
                conversation=conversation,
                save_turn=_save_turn,
                log_cancelled=_log_run_cancelled,
            )
        except HTTPException:
            raise
        except UnexpectedModelBehavior:
            # Model-output validation failures keep existing behavior
            # (the frontend auto-recovery in useAISDKChat handles them).
            raise
        except Exception as exc:
            # NOTE: Model-side 500s (strict chat templates rejecting
            # the message shape, auth failures, overloaded servers)
            # used to surface as an opaque 500 dump. Log the full body
            # server-side, send a readable summary: the frontend shows
            # it and the failed-send recovery can act on it.
            logger.exception("chat model request failed")
            _record_chat_outcome(success=False)
            text = str(exc)
            hint = _chat_error_hint(text)
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Model '{model_id or sessions.active_model}' "
                    f"returned an error: {text[:300]}.{hint}"
                ),
            ) from exc
