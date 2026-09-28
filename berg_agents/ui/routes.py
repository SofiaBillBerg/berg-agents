"""HTTP endpoints for the berg_agents web API.

One router, one injected harness, one injected session store. Every
path here is consumed by the Next.js frontend (``webapp/app`` hook,
components, and ``App.tsx``). Paths are renamed in lockstep with the
frontend; the frontend is the contract authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import logging
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.schemas import (
    ActiveProvider,
    HitlAckResponse,
    HitlDecision,
    ProviderInfo,
    ProviderListResponse,
    ThreadResponse,
    ThreadStatusResponse,
    HarnessRequest,
)
from berg_agents.ui.sessions import SessionManager
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse

logger = logging.getLogger(__name__)


def _require_thread(sessions: SessionManager, thread_id: str) -> None:
    """Raise 404 when a thread id is unknown.

    :param sessions: Session store to check.
    :param thread_id: Thread id to validate.
    :raises HTTPException: 404 when the thread does not exist.
    """
    if not sessions.has(thread_id):
        raise HTTPException(
            status_code=404, detail=f"Thread '{thread_id}' not found"
        )


def _to_ui_message_parts(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate an internal harness event to UI-message-stream parts.

    Lifecycle events travel as AI SDK ``data-*`` parts so a
    ``useChat`` client consumes them via ``onData``; failures use the
    protocol ``error`` part. Internal store shapes are unchanged -
    translation happens at the SSE boundary only.

    :param event: Internal event with ``type`` and ``data`` keys.
    :return: One or more UI-message-stream parts.
    """
    kind = event.get("type")
    data = event.get("data", {})
    if kind == "task_failed":
        reason = (
            data.get("error", "Task failed")
            if isinstance(data, dict)
            else str(data)
        )
        return [{"type": "error", "errorText": str(reason)}]
    part_type = f"data-{str(kind).replace('_', '-')}"
    return [{"type": part_type, "data": data}]


def _requested_model_metadata(
    request: HarnessRequest, sessions: SessionManager
) -> dict[str, Any]:
    """Stash the session-active model into task metadata.

    The session-active model overrides ``request.model``; the
    harness treats ``metadata["requested_model"]`` as an
    explicit override of complexity-default routing.

    :param request: Validated harness request.
    :param sessions: Session store holding the active model.
    :return: Metadata mapping with the override stashed.
    """
    metadata = dict(request.metadata or {})
    active = sessions.active_model or request.model
    if active:
        metadata["requested_model"] = active
    return metadata


async def _resume_after_review(
    thread_id: str,
    task: dict[str, Any],
    harness: Harness,
    sessions: SessionManager,
) -> None:
    """Park for the human decision, then resume the task with it.

    On approve the task re-executes with ``hitl_decision`` merged
    into its metadata; on reject (or dismiss) a ``task_failed``
    event records why nothing resumed.

    :param thread_id: Owning thread id.
    :param task: Task mapping from the original request.
    :param harness: Shared harness instance.
    :param sessions: Session store for events and results.
    """
    # Park until the human decision lands, then resume with it.
    decision = await sessions.wait_for_decision(thread_id)
    # Treat "edit" as approve for now (edited args applied by caller
    # through the action payload); reject/dismiss stops the task.
    if decision in {"approve", "edit"}:
        description = str(task.get("description", ""))
        # On "edit" the reviewer supplied replacement arguments;
        # surface them to the model so it honours the chosen path.
        edited = sessions.get_hitl_edited_action(thread_id)
        if decision == "edit" and edited:
            description += (
                "\n\n[Reviewer override - use exactly these tool "
                f"arguments: {json.dumps(edited, default=str)}]"
            )
        else:
            # Plain approve: surface the pre-planned actions from the
            # gated result so the model executes exactly the shown
            # plan (same paths the human approved on the HITL card).
            prior = sessions.get_result(thread_id) or {}
            planned = prior.get("action_requests")
            if isinstance(planned, list) and planned:
                description += (
                    "\n\n[Approved plan - execute exactly these "
                    f"actions: {json.dumps(planned, default=str)}]"
                )
        resumed = await asyncio.to_thread(
            harness.execute_task,
            {
                **task,
                "description": description,
                "metadata": {
                    **(task.get("metadata") or {}),
                    "hitl_decision": decision,
                },
            },
            task_id=thread_id,
        )
        sessions.set_result(thread_id, resumed)
        sessions.push_event(
            thread_id, {"type": "task_completed", "data": resumed}
        )
    else:
        sessions.push_event(
            thread_id,
            {
                "type": "task_failed",
                "data": {
                    "error": (
                        f"HITL {decision or 'dismissed'}; task not resumed"
                    )
                },
            },
        )


async def _resume_sync_task(
    thread_id: str,
    task: dict[str, Any],
    harness: Harness,
    sessions: SessionManager,
) -> None:
    """Resume an adopted sync-gated task, then close its stream.

    ``POST /api/harness`` already returned ``needs_human_review``,
    so the `resume` parks exactly like the streaming path and
    closes the thread's stream when the decision resolves.

    :param thread_id: Adopted sync task id.
    :param task: Task mapping from the original request.
    :param harness: Shared harness instance.
    :param sessions: Session store for events and results.
    """
    try:
        await _resume_after_review(thread_id, task, harness, sessions)
    finally:
        sessions.finish(thread_id)


async def _run_stream_task(
    thread_id: str,
    request: HarnessRequest,
    harness: Harness,
    sessions: SessionManager,
) -> None:
    """Execute a task in the background, publishing SSE events.

    The blocking harness runs in a worker thread so the event loop
    stays responsive. When the result needs human review, the worker
    parks in :meth:`SessionManager.wait_for_decision` and resumes
    with the recorded decision once it lands.

    :param thread_id: Owning thread id.
    :param request: Validated harness request.
    :param harness: Shared harness instance.
    :param sessions: Session store for events and results.
    """
    task: dict[str, Any] = {
        "description": request.description,
        "task_type": request.task_type,
        "metadata": _requested_model_metadata(request, sessions),
    }
    try:
        result = await asyncio.to_thread(
            harness.execute_task, task, task_id=thread_id
        )
        sessions.set_result(thread_id, result)
        if result.get("status") == "needs_human_review":
            sessions.push_event(
                thread_id,
                {
                    "type": "hitl_requested",
                    "data": {
                        "reasons": result.get("review_reasons", []),
                        "risk_level": result.get("risk_level"),
                        "complexity": result.get("complexity"),
                        "action_requests": result.get("action_requests", []),
                    },
                },
            )
            # Park until the human decision lands, then resume.
            await _resume_after_review(thread_id, task, harness, sessions)
        else:
            sessions.push_event(
                thread_id, {"type": "task_completed", "data": result}
            )
    except asyncio.CancelledError:
        sessions.push_event(
            thread_id,
            {"type": "task_cancelled", "data": {"thread_id": thread_id}},
        )
        raise
    # ruff: ignore[blind-except] - surfaced as UI event
    except Exception as exc:
        logger.exception("Stream task failed for thread %s", thread_id)
        sessions.push_event(
            thread_id, {"type": "task_failed", "data": {"error": str(exc)}}
        )
    finally:
        sessions.finish(thread_id)


def _thread_markdown(thread_id: str, sessions: SessionManager) -> str:
    """Render a thread's events and result as Markdown.

    :param thread_id: Thread id to export.
    :param sessions: Session store to read.
    :return: Markdown document.
    """
    lines = [f"# Thread {thread_id}", ""]
    for event in sessions.event_log(thread_id):
        lines.extend([
            f"## {event.get('type', 'event')}",
            "```json",
            json.dumps(event.get("data", {}), indent=2, default=str),
            "```",
            "",
        ])
    result = sessions.get_result(thread_id)
    if result is not None:
        lines.extend([
            "## result",
            "```json",
            json.dumps(result, indent=2, default=str),
            "```",
        ])
    return "\n".join(lines)


def _register_thread_routes(
    router: APIRouter, sessions: SessionManager
) -> None:
    """Register thread lifecycle, cancellation, and export endpoints.

    :param router: Router to attach endpoints to.
    :param sessions: Session store for thread state.
    """

    @router.post("/api/threads")
    async def create_thread() -> ThreadResponse:
        """
        Create thread.

        :return: Description of return value.

        Example::

            >>> result = create_thread()
        """
        return ThreadResponse(thread_id=sessions.create_thread())

    @router.post("/api/threads/{thread_id}/cancel")
    async def cancel_task(thread_id: str) -> ThreadStatusResponse:
        """
        Cancel task.

        :param thread_id: Thread id to cancel.
        :return: The thread id and status of the cancelled task.

        Example::

            >>> result = cancel_task(thread_id="example_thread_id")
        """
        _require_thread(sessions, thread_id)
        sessions.cancel(thread_id)
        return ThreadStatusResponse(thread_id=thread_id, status="cancelled")

    @router.get("/threads/{thread_id}/export")
    async def export_thread(thread_id: str) -> PlainTextResponse:
        """
        Export thread.

        :param thread_id: Thread id to export.
        :return: Plain text response containing the thread's events and result in Markdown format.

        Example::

            >>> result = export_thread(thread_id="example_thread_id")
        """
        _require_thread(sessions, thread_id)
        return PlainTextResponse(
            _thread_markdown(thread_id, sessions), media_type="text/markdown"
        )

    @router.get("/api/threads/{thread_id}")
    async def get_thread_json(thread_id: str) -> dict[str, Any]:
        """JSON export for live clients - replaces markdown parse hack.

        :param thread_id: Thread id to export.
        :return: Dictionary containing the thread's events and result.

        Example::

            >>> result = get_thread_json(thread_id="example_thread_id")
        """
        _require_thread(sessions, thread_id)
        return {
            "thread_id": thread_id,
            "events": sessions.event_log(thread_id),
            "result": sessions.get_result(thread_id),
        }

    @router.delete("/api/threads/{thread_id}")
    async def delete_thread(thread_id: str) -> dict[str, str]:
        """Delete a thread's history.

        :param thread_id: Thread id to delete.
        :return: Dictionary indicating the status of the deletion and the thread id.
        """
        _require_thread(sessions, thread_id)
        # Fully clean up all thread state
        sessions.delete(thread_id)
        return {"status": "deleted", "thread_id": thread_id}


def _register_provider_routes(
    router: APIRouter,
    sessions: SessionManager,
    providers: list[dict[str, Any]],
) -> None:
    """Register provider listing and selection endpoints.

    :param router: Router to attach endpoints to.
    :param sessions: Session store holding the active selection.
    :param providers: Configured provider/model pairs.
    """

    @router.get("/api/providers")
    async def list_providers() -> ProviderListResponse:
        """
        List providers.

        :return: A ProviderListResponse object containing a list of available providers and their information.

        Example::

            >>> result = list_providers()
        """
        return ProviderListResponse(
            providers=[ProviderInfo(**item) for item in providers]
        )

    @router.get("/api/providers/active")
    async def get_active_provider() -> ActiveProvider:
        """
        Get active provider.


        :return: An ActiveProvider object containing the currently active provider and model.

        Example::

            >>> result = get_active_provider()
        """
        return ActiveProvider(
            provider=sessions.active_provider, model=sessions.active_model
        )

    @router.post("/api/providers/active")
    async def set_active_provider(selection: ActiveProvider) -> ActiveProvider:
        """Switch the active provider/model pair.

        :param selection: An ActiveProvider object containing the provider and model to set as active.
        :return: The ActiveProvider object that was set as active.

        Example::

            >>> result = set_active_provider(ActiveProvider(provider="openai", model="gpt-3.5"))
        """
        sessions.active_provider = selection.provider
        sessions.active_model = selection.model
        return selection


def create_router(
    harness: Harness,
    sessions: SessionManager,
    *,
    providers: list[dict[str, Any]],
) -> APIRouter:
    """Build the API router with injected dependencies.

    :param harness: Shared harness (single instance per app).
    :param sessions: Session store for threads, events, and HITL state.
    :param providers: Configured provider/model pairs.
    :return: Configured APIRouter.
    """
    router = APIRouter()

    @router.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """
        List all registered agents.

        :return: A list of dictionaries containing information about each agent.

        Example::

            >>> result = list_agents()
        """
        return harness.get_agent_info()

    @router.get("/api/agents/{name}")
    async def get_agent(name: str) -> dict[str, Any]:
        """
        Return info for one agent by name.

        :param name: The name of the agent to retrieve.
        :return: A dictionary containing information about the specified agent.
        """
        try:
            return harness.get_agent(name).get_info()
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Agent '{name}' not found"
            ) from None

    @router.post("/api/harness")
    async def run_harness(request: HarnessRequest) -> dict[str, Any]:
        """Execute a task synchronously and return its result.

        A gated result adopts its task id into the session store
        and resumes in the background, so approve/reject via
        ``/respond`` finds the thread instead of 404ing.

        :param request: Validated harness request.
        :return: Result of the task execution, or a gated result indicating human review is needed
        """
        task: dict[str, Any] = {
            "description": request.description,
            "task_type": request.task_type,
            "metadata": _requested_model_metadata(request, sessions),
        }
        result = await asyncio.to_thread(harness.execute_task, task)
        # Defensive: upstream may still return a list; normalize to dict
        if isinstance(result, list) and result:
            result = result[0] if isinstance(result[0], dict) else {}
        if (
            isinstance(result, dict)
            and result.get("status") == "needs_human_review"
        ):
            thread_id = str(result.get("task_id") or "")
            if thread_id:
                # Adopt the harness-made id: the UI answers it via
                # /respond while the worker parks/resumes on it.
                sessions.adopt_thread(thread_id)
                sessions.set_result(thread_id, result)
                sessions.push_event(
                    thread_id,
                    {
                        "type": "hitl_requested",
                        "data": {
                            "reasons": result.get("review_reasons", []),
                            "risk_level": result.get("risk_level"),
                            "complexity": result.get("complexity"),
                            "action_requests": result.get("action_requests")
                            or result.get("planned_actions")
                            or [],
                        },
                    },
                )
                sessions.start_background(
                    thread_id,
                    _resume_sync_task(thread_id, task, harness, sessions),
                )
        return result

    @router.post("/api/harness/{thread_id}/stream")
    async def submit_task_stream(
        thread_id: str, request: HarnessRequest
    ) -> ThreadStatusResponse:
        """Start background execution for a thread (SSE via /events).


        :param thread_id: Thread id to execute.
        :param request: Validated harness request.
        :return: ThreadStatusResponse indicating the thread has started.
        """
        _require_thread(sessions, thread_id)
        sessions.push_event(
            thread_id,
            {
                "type": "task_started",
                "data": {
                    "description": request.description,
                    "task_type": request.task_type,
                },
            },
        )
        sessions.start_background(
            thread_id,
            _run_stream_task(thread_id, request, harness, sessions),
        )
        return ThreadStatusResponse(thread_id=thread_id, status="started")

    @router.get("/api/harness/{thread_id}/events")
    async def stream_events(thread_id: str) -> StreamingResponse:
        """Stream a thread's events as AI SDK UI-message-stream parts.

        Internal harness events are translated at this boundary; the
        ``v1`` header marks the stream for AI SDK clients. No-cache /
        keep-alive headers keep buffering proxies from holding back
        the stream; the frontend client needs each ``data:`` line as
        it is published.

        :param thread_id: Thread id to stream.
        :return: StreamingResponse yielding events as Server-Sent Events (SSE) in the
        """
        _require_thread(sessions, thread_id)

        async def event_body() -> AsyncIterator[str]:
            """Generate the event body for the streaming response.

            :yield: Each event as a JSON-encoded string in the format of Server-Sent Events (SSE).
            """
            async for event in sessions.events(thread_id):
                for part in _to_ui_message_parts(event):
                    yield f"data: {json.dumps(part, default=str)}\n\n"

        return StreamingResponse(
            event_body(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "x-vercel-ai-ui-message-stream": "v1",
            },
        )

    @router.post("/api/harness/{thread_id}/respond")
    async def respond_to_hitl(
        thread_id: str, response: HitlDecision
    ) -> HitlAckResponse:
        """Record a human decision for a thread awaiting review."""
        _require_thread(sessions, thread_id)
        sessions.set_hitl_decision(
            thread_id, response.decision, edited_action=response.edited_action
        )
        return HitlAckResponse(
            thread_id=thread_id, status="ok", decision=response.decision
        )

    @router.get("/api/learning-stats")
    async def learning_stats() -> dict[str, Any]:
        """Return learning/outcome statistics.

        :return: A dictionary containing learning statistics.
        """
        return harness.get_learning_stats()

    _register_thread_routes(router, sessions)
    _register_provider_routes(router, sessions, providers)
    return router
