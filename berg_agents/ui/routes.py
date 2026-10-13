"""HTTP endpoints for the berg_agents web API.

All routes consumed by the Next.js frontend (``webapp/app``).
The streaming chat endpoint uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter`
for native Vercel AI SSE protocol - no manual event-loop / SSE translation needed.
"""

from __future__ import annotations

import asyncio
import logging
from functools import cached_property
from typing import Any

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

from berg_agents.core.harness import Harness
from berg_agents.ui.schemas import (
    ActiveProvider,
    ProviderInfo,
    ProviderListResponse,
    SessionCreateRequest,
    SessionRenameRequest,
    SubtaskCreateRequest,
    SubtaskUpdateRequest,
    TodoCreateRequest,
    TodoUpdateRequest,
    ToolExecuteRequest,
    ToolExecuteResponse,
)
from berg_agents.ui.sessions import SessionManager

logger = logging.getLogger(__name__)


def _shared_todo_dir() -> str:
    """Directory backing both the agent todo tools and the plugin UI.

    :return: Todo directory (same default the tools use, so the model
        and the side-panel always read the same Markdown store).
    """
    return "./sharedtodos/"


def _ensure_shared_todo_importable() -> None:
    """Put the shared-todo pilot package on ``sys.path`` (idempotent).

    PluginManager does this too when it imports the plugin; the endpoint
    must not depend on load ordering, so it ensures it as well.
    """
    import sys
    from pathlib import Path

    # NOTE: routes.py lives at berg_agents/ui/, so the checkout root
    # is two parents up.
    plugin_dir = (
        Path(__file__).resolve().parents[2] / "berg_plugins" / "shared-todo"
    )
    if plugin_dir.is_dir():
        path_str = str(plugin_dir)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)


class BergVercelAIAdapter(VercelAIAdapter):
    """Vercel AI adapter with per-step HITL approval support.

    The stock adapter maps each answered approval to a bare ``True`` or
    ``False``. That discards the arguments the user edited in the UI
    before approving. This subclass instead maps an *approved* call to
    :class:`ToolApproved` carrying the part's ``input`` as
    ``override_args``: the part's input is the original call's args
    when untouched (a no-op override) and the user's edited args when
    they revised them, so edits reach the actual tool execution.

    Denials keep the stock behaviour (``False``, or
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
        """List all configured provider/model pairs.

        :return: Provider list response.
        """
        return ProviderListResponse(
            providers=[ProviderInfo(**item) for item in providers]
        )

    @router.get("/api/providers/active")
    async def get_active_provider() -> ActiveProvider:
        """Get the currently active provider/model pair.

        :return: Active provider response.
        """
        return ActiveProvider(
            provider=sessions.active_provider, model=sessions.active_model
        )

    @router.post("/api/providers/active")
    async def set_active_provider(selection: ActiveProvider) -> ActiveProvider:
        """Switch the active provider/model pair.

        :param selection: Provider/model to activate.
        :return: The activated provider/model.
        """
        sessions.active_provider = selection.provider
        sessions.active_model = selection.model
        return selection


def _unique_ui_message_id(msg: Any, role: str, index: int) -> str:
    """Message ids for restored sessions (React keys + SDK identity).

    The adapter default restores the original client id per ModelMessage —
    but one ModelRequest carrying both system and user parts dumps to TWO
    UIMessages with that same id, which React rejects as duplicate keys.
    Namespacing by role keeps ids deterministic (stable across reloads)
    and unique.
    """
    # NOTE: Reuses the adapter default, then disambiguates. Same reader
    # the chat path uses, so restored ids stay consistent with live ones.
    from pydantic_ai.ui.vercel_ai._adapter import _generate_message_id

    return f"{_generate_message_id(msg, role, index)}-{role}-{index}"


def create_router(
    harness: Harness,
    sessions: SessionManager,
    *,
    providers: list[dict[str, Any]],
) -> APIRouter:
    """Build the API router with injected dependencies.

    :param harness: Shared harness (single instance per app).
    :param sessions: Session store (needed for model override in chat).
    :param providers: Configured provider/model pairs.
    :return: Configured APIRouter.
    """
    router = APIRouter()

    @router.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """List all registered agents.

        :return: A list of dictionaries containing information about each agent.
        """
        return harness.get_agent_info()

    @router.get("/api/agents/{name}")
    async def get_agent(name: str) -> dict[str, Any]:
        """Return info for one agent by name.

        :param name: The name of the agent to retrieve.
        :return: A dictionary containing information about the specified agent.
        :raises HTTPException: 404 when the agent name is unknown.
        """
        try:
            return harness.get_agent(name).get_info()
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Agent '{name}' not found"
            ) from None

    @router.post("/api/chat/stream")
    async def chat_stream(
        request: Request,
    ) -> Response:
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
        (``.berg_config/bergagents.jsonc`` and ``.berg_config/profiles.yaml``) - never
        hardcoded. An optional ``?model=`` query param overrides the model.

        :param request: FastAPI request - VercelAIAdapter inspects the body
            and ``accept`` header to pick the protocol and parse messages.
        :return: StreamingResponse with SSE chunks in Vercel AI protocol.
        """
        from berg_agents.agents.chat_agent import build_chat_agent
        from berg_agents.plugin_system.chat_integration import (
            get_chat_plugin_state,
        )

        # Model override via query param (the body is consumed by the adapter).
        model_id = (
            request.query_params.get("model") or sessions.active_model or ""
        )

        # NOTE: Server-side session (any browser, any profile). The
        # frontend sends its session id in the body; the authoritative
        # transcript is saved on completion. All failure-isolated:
        # sessions must never break chat.
        session_id: str | None = None
        try:
            from berg_agents.ui import session_store

            body = await request.json()
            raw_session = (
                body.get("sessionId") if isinstance(body, dict) else None
            )
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
        except Exception as exc:
            logger.warning("Session tracking skipped: %s", exc)
            session_id = None
        # NOTE: Plugin state is per-turn and failure-isolated: a broken
        # plugin dir only logs, chat still gets its agent. Disabled
        # plugins are withheld from tools, MCP toolsets, and skills.
        (
            plugin_tools,
            disabled_mcp,
            disabled_skills,
        ) = await get_chat_plugin_state()
        agent = build_chat_agent(
            model_id,
            root_dir=sessions._harness_root_dir(),
            plugin_tools=plugin_tools,
            disabled_mcp=disabled_mcp,
            disabled_skills=disabled_skills,
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

        async def _log_run_cancelled(run_cancelled: object) -> None:
            # Fired when a client stop/disconnect cancels the run, so
            # the "Stop" button is observable server-side.
            logger.info("chat run cancelled: %s", run_cancelled)

        async def _save_turn(result: Any) -> None:
            # on_complete receives the AgentRunResult: persist the
            # authoritative transcript so any browser can resume it.
            if not session_id:
                return
            try:
                from berg_agents.ui import session_store

                store = session_store.get_store(sessions._harness_root_dir())
                await session_store.record_turn(
                    store, session_id, result.all_messages()
                )
            except Exception as exc:
                logger.warning("Session save skipped: %s", exc)

        async def _dispatch_with_empty_stream_retry() -> Response:
            # Proxy hiccups (observed via omniroute) can return an
            # entirely empty SSE stream; pydantic-ai surfaces that as
            # UnexpectedModelBehavior("... ended without content ...").
            # The failed step produced no assistant turn and executed
            # nothing, so re-sending the same request is safe: the
            # body is cached by Starlette and the retry simply
            # regenerates the missing turn instead of failing the chat.
            for attempt in (1, 2):
                try:
                    return await BergVercelAIAdapter.dispatch_request(
                        request,
                        agent=agent,
                        sdk_version=6,
                        output_type=[str, DeferredToolRequests],
                        conversation_id=session_id,
                        on_complete=_save_turn,
                        on_cancel=_log_run_cancelled,
                    )
                except UnexpectedModelBehavior as exc:
                    if "ended without content" not in str(exc):
                        raise
                    if attempt == 2:
                        logger.error(
                            "chat stream empty twice - giving up: %s", exc
                        )
                        raise
                    logger.warning(
                        "chat stream ended empty (attempt %s/2) - retrying",
                        attempt,
                    )
                    await asyncio.sleep(2)
            raise AssertionError("unreachable")  # pragma: no cover

        try:
            return await _dispatch_with_empty_stream_retry()
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
            logger.error("chat model request failed: %s", exc)
            text = str(exc)
            hint = ""
            lowered = text.lower()
            if "system message" in lowered or "jinja" in lowered:
                hint = (
                    " This model enforces strict chat-template rules "
                    "(system-prompt placement) and rejected the request "
                    "shape — try another model."
                )
            elif "401" in lowered or "auth" in lowered:
                hint = " Check the provider API key for this model."
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Model '{model_id or sessions.active_model}' "
                    f"returned an error: {text[:300]}.{hint}"
                ),
            ) from exc

    @router.get("/api/plugins")
    async def list_plugins() -> dict[str, Any]:
        """List discovered plugins and their chat tools.

        Powers the web UI plugin surfaces (side-panel/canvas): the
        frontend matches tool calls against these names to decide
        when to render a plugin view instead of a generic tool card.

        :return: Dict with ``plugins`` descriptors.
        """
        from berg_agents.plugin_system.chat_integration import (
            list_chat_plugins,
        )

        return {"plugins": await list_chat_plugins()}

    @router.get("/api/plugins/todos")
    async def list_todos_endpoint(
        status: str | None = None,
    ) -> dict[str, Any]:
        """List shared-todo items as structured data for the plugin UI.

        Reads the same Markdown store the agent's todo tools write,
        so the side-panel/canvas and the model always see the same list.

        :param status: Optional filter (todo, in_progress, done).
        :return: Dict with ``todos`` items.
        """
        from berg_agents.ui.schemas import TodoItem

        _ensure_shared_todo_importable()
        from shared_todo.tools import list_todo_items

        items = await asyncio.to_thread(
            list_todo_items, status, _shared_todo_dir()
        )
        return {"todos": [TodoItem(**item).model_dump() for item in items]}

    @router.post("/api/plugins/todos")
    async def create_todo_endpoint(
        request: TodoCreateRequest,
    ) -> dict[str, Any]:
        """Create a shared-todo item from the plugin UI.

        :param request: Title plus optional description.
        :return: Dict with the created item ``id``.
        :raises HTTPException: 400 when the title is blank.
        """
        if not request.title.strip():
            raise HTTPException(
                status_code=400, detail="Title must not be blank."
            )
        _ensure_shared_todo_importable()
        from shared_todo.tools import create_todo, list_todo_items

        await asyncio.to_thread(
            create_todo,
            request.title.strip(),
            request.description,
            _shared_todo_dir(),
        )
        todo_id = (
            # NOTE: Mirrors the tool's slugging algorithm so the
            # response can echo the created item; keep in sync with
            # shared_todo.tools.create_todo.
            request.title
            .strip()
            .lower()
            .replace(" ", "_")
            .replace("/", "_")[:50]
        )
        created = await asyncio.to_thread(
            list_todo_items, None, _shared_todo_dir()
        )
        match = next((item for item in created if item["id"] == todo_id), None)
        return {"id": todo_id, "todo": match}

    @router.patch("/api/plugins/todos/{todo_id}")
    async def update_todo_endpoint(
        todo_id: str, request: TodoUpdateRequest
    ) -> dict[str, Any]:
        """Update a shared-todo item from the plugin UI.

        :param todo_id: Todo identifier.
        :param request: Any subset of title/description/status.
        :return: Dict with ``ok`` plus the tool output message.
        :raises HTTPException: 404 when the todo does not exist.
        """
        _ensure_shared_todo_importable()
        from shared_todo.tools import update_todo

        output = await asyncio.to_thread(
            update_todo,
            todo_id,
            request.title,
            request.description,
            request.status,
            _shared_todo_dir(),
        )
        if output.startswith("Error:"):
            raise HTTPException(status_code=404, detail=output)
        return {"ok": True, "output": output}

    @router.delete("/api/plugins/todos/{todo_id}")
    async def delete_todo_endpoint(todo_id: str) -> dict[str, Any]:
        """Delete a shared-todo item from the plugin UI.

        :param todo_id: Todo identifier.
        :return: Dict with ``ok`` plus the tool output message.
        :raises HTTPException: 404 when the todo does not exist.
        """
        _ensure_shared_todo_importable()
        from shared_todo.tools import delete_todo

        output = await asyncio.to_thread(
            delete_todo, todo_id, _shared_todo_dir()
        )
        if output.startswith("Error:"):
            raise HTTPException(status_code=404, detail=output)
        return {"ok": True, "output": output}

    @router.post("/api/plugins/todos/{todo_id}/subtasks")
    async def create_subtask_endpoint(
        todo_id: str, request: SubtaskCreateRequest
    ) -> dict[str, Any]:
        """Append a subtask checklist item to a todo.

        :param todo_id: Todo identifier.
        :param request: Subtask text.
        :return: Dict with ``ok`` plus the tool output message.
        :raises HTTPException: 400 for blank text, 404 for unknown todos.
        """
        if not request.text.strip():
            raise HTTPException(
                status_code=400, detail="Subtask text must not be blank."
            )
        _ensure_shared_todo_importable()
        from shared_todo.tools import add_subtask

        output = await asyncio.to_thread(
            add_subtask, todo_id, request.text.strip(), _shared_todo_dir()
        )
        if output.startswith("Error:"):
            raise HTTPException(status_code=404, detail=output)
        return {"ok": True, "output": output}

    @router.patch("/api/plugins/todos/{todo_id}/subtasks/{index}")
    async def update_subtask_endpoint(
        todo_id: str, index: int, request: SubtaskUpdateRequest
    ) -> dict[str, Any]:
        """Check or uncheck a subtask by index.

        :param todo_id: Todo identifier.
        :param index: Subtask index in file order (from 0).
        :param request: Desired checked state.
        :return: Dict with ``ok`` plus the tool output message.
        :raises HTTPException: 404 for unknown todos or indices.
        """
        _ensure_shared_todo_importable()
        from shared_todo.tools import set_subtask_done

        output = await asyncio.to_thread(
            set_subtask_done, todo_id, index, request.done, _shared_todo_dir()
        )
        if output.startswith("Error:"):
            raise HTTPException(status_code=404, detail=output)
        return {"ok": True, "output": output}

    @router.delete("/api/plugins/todos/{todo_id}/subtasks/{index}")
    async def delete_subtask_endpoint(
        todo_id: str, index: int
    ) -> dict[str, Any]:
        """Delete a subtask by index (later items shift down).

        :param todo_id: Todo identifier.
        :param index: Subtask index in file order (from 0).
        :return: Dict with ``ok`` plus the tool output message.
        :raises HTTPException: 404 for unknown todos or indices.
        """
        _ensure_shared_todo_importable()
        from shared_todo.tools import delete_subtask

        output = await asyncio.to_thread(
            delete_subtask, todo_id, index, _shared_todo_dir()
        )
        if output.startswith("Error:"):
            raise HTTPException(status_code=404, detail=output)
        return {"ok": True, "output": output}

    @router.post("/api/plugins/{plugin_id}/enable")
    async def enable_plugin_endpoint(plugin_id: str) -> dict[str, Any]:
        """Enable a plugin (its tools rejoin the chat agent).

        :param plugin_id: Plugin identifier.
        :return: Dict with the plugin ``id`` and new ``state``.
        :raises HTTPException: 404 for unknown plugin ids.
        """
        from berg_agents.plugin_system.chat_integration import (
            set_plugin_enabled,
        )

        state = await set_plugin_enabled(plugin_id, True)
        if state is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown plugin '{plugin_id}'."
            )
        return {"id": plugin_id, "state": state}

    @router.post("/api/plugins/{plugin_id}/disable")
    async def disable_plugin_endpoint(plugin_id: str) -> dict[str, Any]:
        """Disable a plugin (its tools leave the chat agent).

        MCP servers stop attaching toolsets, todo tools stop being
        offered, and skills stop loading — all from the next chat turn.

        :param plugin_id: Plugin identifier.
        :return: Dict with the plugin ``id`` and new ``state``.
        :raises HTTPException: 404 for unknown plugin ids.
        """
        from berg_agents.plugin_system.chat_integration import (
            set_plugin_enabled,
        )

        state = await set_plugin_enabled(plugin_id, False)
        if state is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown plugin '{plugin_id}'."
            )
        return {"id": plugin_id, "state": state}

    @router.get("/api/sessions")
    async def list_sessions(q: str = "", limit: int = 100) -> dict[str, Any]:
        """List server-side chat sessions (newest first, searchable).

        The authoritative session list for every browser: unlike the
        localStorage snapshots, these survive profile switches.

        :param q: Full-text filter over titles and transcripts.
        :param limit: Max sessions returned.
        :return: Dict with ``sessions`` summaries.
        """
        from berg_agents.ui import session_store

        store = session_store.get_store(sessions._harness_root_dir())
        found = await store.listing(
            query=q or "", limit=max(1, min(limit, 200))
        )
        return {"sessions": [session_store.summary_to_dict(s) for s in found]}

    @router.get("/api/sessions/current")
    async def get_current_session() -> dict[str, Any]:
        """Return the converged-upon active session id (may be null).

        Fresh browsers adopt this instead of minting divergent sessions,
        so every window lands on the same conversation.

        :return: Dict with ``id`` (or null).
        """
        from berg_agents.ui import session_store

        return {
            "id": session_store.get_active_session(sessions._harness_root_dir())
        }

    @router.post("/api/sessions/current")
    async def set_current_session(request: dict[str, Any]) -> dict[str, Any]:
        """Point the project at one session (restore / new chat / send).

        :param request: Mapping with the session ``id``.
        :return: Dict with the adopted ``id``.
        :raises HTTPException: 404 for unknown session ids.
        """
        from berg_agents.ui import session_store

        raw = request.get("id") if isinstance(request, dict) else None
        session_id = session_store.coerce_session_id(raw)
        if raw != session_id:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{raw}'."
            )
        root = sessions._harness_root_dir()
        store = session_store.get_store(root)
        try:
            await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        session_store.set_active_session(root, session_id)
        return {"id": session_id}

    @router.post("/api/sessions")
    async def create_session(
        request: SessionCreateRequest | None = None,
    ) -> dict[str, Any]:
        """Create a server-side chat session.

        Titles default to ``<project> #<seq> · <date>`` (never the first
        "hello"); pass an explicit title or rename later.

        :param request: Optional explicit title.
        :return: The created session summary.
        """
        from berg_agents.ui import session_store

        root = sessions._harness_root_dir()
        store = session_store.get_store(root)
        session_id = session_store.coerce_session_id(None)
        summary = await session_store.ensure_session(
            store,
            session_id,
            workspace=session_store.project_name(root),
            model=sessions.active_model,
        )
        if request and request.title and request.title.strip():
            await store.name(
                source=summary,
                title=request.title.strip()[:80],
                manual=True,
            )
            summary = (await store.get(conversation_id=session_id)).summary
        session_store.set_active_session(root, session_id)
        return session_store.summary_to_dict(summary)

    @router.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Load one session with UI messages for restoring in chat.

        Converts the stored framework messages at the edge
        (``dump_messages``) for the hook to consume.

        :param session_id: Session identifier.
        :return: Summary plus ``messages`` in Vercel AI UI shape.
        :raises HTTPException: 404 for unknown sessions.
        """
        from pydantic_ai.ui.vercel_ai import VercelAIAdapter

        from berg_agents.ui import session_store

        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        ui_messages = VercelAIAdapter.dump_messages(
            saved.messages,
            sdk_version=6,
            generate_message_id=_unique_ui_message_id,
        )
        return {
            "session": session_store.summary_to_dict(saved.summary),
            "messages": [m.model_dump(mode="json") for m in ui_messages]}

    @router.patch("/api/sessions/{session_id}")
    async def rename_session(
        session_id: str, request: SessionRenameRequest
    ) -> dict[str, Any]:
        """Rename a session (explicit user title, wins over generated).

        :param session_id: Session identifier.
        :param request: New title.
        :return: Updated session summary.
        :raises HTTPException: 404 for unknown sessions.
        """
        from berg_agents.ui import session_store

        if not request.title.strip():
            raise HTTPException(
                status_code=400, detail="Title must not be blank."
            )
        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        await store.name(
            source=saved.summary,
            title=request.title.strip()[:80],
            manual=True,
        )
        updated = await store.get(conversation_id=session_id)
        return session_store.summary_to_dict(updated.summary)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        """Delete a server-side session and its transcript.

        :param session_id: Session identifier.
        :return: Dict with ``ok``.
        :raises HTTPException: 404 for unknown sessions, 409 when busy.
        """
        from pydantic_ai_harness.step_persistence.conversations import (
            ConversationConflict,
        )

        from berg_agents.ui import session_store

        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        try:
            await store.delete(source=saved.summary)
        except ConversationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True}

    @router.get("/api/tools")
    async def list_tools() -> dict[str, Any]:
        """List tools the ``/api/tool/execute`` endpoint can run.

        Workspace file tools (name + one-line description) plus the
        harness entry points. ``plan_task`` / ``implement_task`` are
        marked ``delegated``: they run inside the chat turn, so the
        web UI routes ``/plan`` / ``/implement`` through ``run_task``
        instead of executing them directly. MCP *servers* are listed
        separately - their live tool names need a running session.

        :return: Dict with ``tools`` and ``mcp_servers`` lists.
        """
        from berg_agents.agents.factory import create_tools
        from berg_agents.capabilities.mcp_toolsets import list_servers

        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "source": "workspace"}
            for spec in create_tools(root_dir=sessions._harness_root_dir())
            if spec.execute is not None
        ]
        tools.extend([
            {
                "name": "run_task",
                "description": (
                    "Run the full harness pipeline on a description."
                ),
                "source": "harness"},
            {
                "name": "plan_task",
                "description": (
                    "Decompose a task into an ordered step plan. "
                    "Runs in chat; the UI routes /plan through run_task."
                ),
                "source": "delegate"},
            {
                "name": "implement_task",
                "description": (
                    "Execute an approved step plan. Runs in chat; "
                    "the UI routes /implement through run_task."
                ),
                "source": "delegate"}])
        return {"tools": tools, "mcp_servers": list_servers()}

    @router.get("/api/context")
    async def context_catalog() -> dict[str, Any]:
        """Catalog of everything the agent may load as context.

        Memory files (``settings.memory``), skills (parsed frontmatter
        only, no bodies), and MCP servers (names + enabled flags -
        live tool names need a running session). Mirrors the TUI
        ``/memory`` ``/skills`` ``/mcps`` listings for the web UI.

        :return: Dict with ``memory``, ``skills``, ``mcp_servers``,
            and the active provider/model.
        """
        from pathlib import Path

        from berg_agents.capabilities.mcp_toolsets import list_servers
        from berg_agents.capabilities.skills import list_skills
        from berg_agents.config.settings import get_settings

        settings = get_settings()
        root = Path(sessions._harness_root_dir()).expanduser().resolve()

        def _exists(entry: Any) -> bool:
            raw = (
                str(entry[0])
                if isinstance(entry, (list, tuple)) and entry
                else str(entry or "")
            )
            if not raw:
                return False
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                return candidate.is_file()
            return (root / candidate).is_file()

        return {
            "memory": [
                {"path": str(m), "exists": _exists(m)}
                for m in (settings.memory or [])
            ],
            "skills": list_skills(
                settings.skills, root_dir=sessions._harness_root_dir()
            ),
            "mcp_servers": list_servers(),
            "active": {
                "provider": sessions.active_provider,
                "model": sessions.active_model}}

    @router.get("/api/learning-stats")
    async def learning_stats() -> dict[str, Any]:
        """Return learning/outcome statistics.

        :return: A dictionary containing learning statistics.
        """
        return harness.get_learning_stats()

    @router.post("/api/tool/execute")
    async def execute_tool(request: ToolExecuteRequest) -> ToolExecuteResponse:
        """Execute one tool synchronously and return its output.

        Switches on the tool name and runs the matching
        :class:`~berg_agents.core.tool_spec.ToolSpec` (file tools)
        or the full harness pipeline (``run_task``). This is the
        endpoint the webapp's ``executeTool`` (slash commands like
        ``/read_file``) calls. Tool functions already return
        human-readable messages instead of raising, so failures
        arrive as ``status="error"`` output - never tracebacks.

        :param request: Tool name plus arguments (mapping, or a bare
            string treated as ``file_path``).
        :return: Tool name, string output, and status.
        :raises HTTPException: 404 for unknown tool names.
        """
        import asyncio

        from berg_agents.agents.factory import create_tools

        name = (request.tool or "").strip()
        args = request.args
        if isinstance(args, str):
            args = {"file_path": args} if args else {}
        if not isinstance(args, dict):
            args = {}

        if name == "run_task":
            task: dict[str, Any] = {
                "description": str(args.get("description", "")),
                "task_type": str(args.get("task_type", "generic")),
                "metadata": {}}
            if not task["description"]:
                return ToolExecuteResponse(
                    tool=name,
                    output="Missing 'description': tell me what to do, "
                    'e.g. /run_task {"description": "summarize README"}.',
                    status="error",
                )
            result = await asyncio.to_thread(
                harness.execute_task, task, task_id=f"tool-{id(task)}"
            )
            if isinstance(result, str):
                output = result
            else:
                import json as _json

                try:
                    output = _json.dumps(result, indent=2, default=str)
                except (TypeError, ValueError):
                    output = str(result)
            return ToolExecuteResponse(tool=name, output=output)

        specs = {
            spec.name: spec
            for spec in create_tools(root_dir=sessions._harness_root_dir())
        }
        spec = specs.get(name)
        if spec is None or spec.execute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tool '{name}'. "
                f"Available: {', '.join(sorted(specs))}, run_task.",
            )
        try:
            result = spec.execute(**args)
            if asyncio.iscoroutine(result):
                result = await result
            output = result if isinstance(result, str) else str(result)
            return ToolExecuteResponse(tool=name, output=output)
        except TypeError as exc:
            # Wrong kwargs (e.g. missing content for write_file).
            return ToolExecuteResponse(
                tool=name,
                output=f"Bad arguments for {name}: {exc}. "
                f'Send {{"file_path": ..., "content": ...}} where needed.',
                status="error",
            )
        except Exception as exc:  # Defensive: never leak tracebacks.
            logger.warning("Tool %s failed: %s", name, exc, exc_info=True)
            return ToolExecuteResponse(
                tool=name, output=f"{name} failed: {exc}", status="error"
            )

    _register_provider_routes(router, sessions, providers)
    return router
