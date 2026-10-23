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

"""HTTP endpoints for the berg_agents web API.

All routes consumed by the Next.js frontend (``webapp/app``).
The streaming chat endpoint uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter`
for native Vercel AI SSE protocol - no manual event-loop / SSE translation needed.
"""

from __future__ import annotations

import asyncio
from functools import cached_property
import json
import logging
import pathlib
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.route_handlers.providers import register_provider_routes
from berg_agents.ui.schemas import (
    SessionCreateRequest,
    SessionRenameRequest,
    ToolExecuteRequest,
    ToolExecuteResponse,
)
from berg_agents.ui.sessions import SessionManager
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

logger = logging.getLogger(__name__)

#: Give up on a chat stream after this many consecutive empty responses.
_MAX_EMPTY_STREAM_ATTEMPTS = 2


async def _run_plugin_tool(
    plugin_id: str,
    tool_name: str,
    args: dict[str, Any],
    root_dir: str,
) -> Any:
    """Run a loaded plugin's tool by name (no todo/shared-todo naming).

    The dispatch resolves the live plugin instance from the warmed
    plugin manager, finds the named tool among the capabilities it
    registered, and calls its underlying function. This is the single
    path plugin UIs use — the host knows only tool names, never the
    plugin's domain.

    :param plugin_id: Plugin identifier.
    :param tool_name: Tool name as declared by the plugin.
    :param args: Keyword arguments for the tool.
    :param root_dir: Project root (plugin config / storage base).
    :return: The tool's return value (usually a string).
    :raises KeyError: When the plugin or tool is unknown.
    """
    from berg_agents.plugin_system.chat_integration import get_chat_plugin_tools
    from berg_agents.plugin_system.lifecycle.lifecycle_states import PluginState

    # Ensure the manager is warm (idempotent, cheap after first call).
    await get_chat_plugin_tools()
    from berg_agents.plugin_system.chat_integration import _CACHE

    manager = _CACHE.get("manager")
    if manager is None:
        raise KeyError(f"Plugin system unavailable: {plugin_id}")
    entry = manager.registry.get(plugin_id)
    if entry is None or entry.state == PluginState.DISCOVERED:
        raise KeyError(f"Unknown plugin: {plugin_id}")
    if entry.state != PluginState.ENABLED:
        raise KeyError(f"Plugin {plugin_id} is not enabled")
    for cap in manager.registry.get_capabilities(
        plugin_id=plugin_id, capability_type="tool"
    ):
        tool = getattr(cap, "tool", None)
        if tool is None:
            continue
        # Names come from the Tool's `name`, but fall back to the
        # wrapped function's __name__ so server-side helpers (which
        # are not model-facing tools) stay callable too.
        candidates = {
            str(getattr(tool, "name", "") or ""),
            str(getattr(getattr(tool, "function", None), "__name__", "") or "")}
        if tool_name not in candidates:
            continue
        function = getattr(tool, "function", tool)
        return function(**args)
    raise KeyError(f"Unknown tool {tool_name} on plugin {plugin_id}")


def _plugin_config_dir(root_dir: str) -> Any:
    """Config dir base for plugin settings, via the shared resolver.

    Precedence: ``BERG_AGENTS_CONFIG_DIR``, project ``.berg-agents/``,
    then global ``~/.berg-agents/``.

    :param root_dir: Project root.
    :return: Absolute path to the resolved config directory.
    """
    from pathlib import Path

    from berg_agents.config.paths import resolve_config_dir

    return resolve_config_dir(Path(root_dir).expanduser().resolve())


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
    from pydantic_ai.ui.vercel_ai._adapter import _generate_message_id  # ruff: ignore[import-private-name]

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
        (``.berg-agents/bergagents.jsonc`` and ``.berg-agents/profiles.yaml``) - never
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
        conversation: Any = None
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
            # Carry the stored Conversation so usage (and the
            # conversation_id) survive across turns. Without it every
            # turn's UsageLimits budget restarts from zero.
            conversation = session_store.load_conversation(session_id)
        except Exception as exc:
            logger.warning("Session tracking skipped: %s", exc)
            session_id = None
            conversation = None
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

        # Learning: chat is the main surface, so its turns feed the same
        # outcome store as harness tasks - otherwise learning never fires.
        def _record_chat_outcome(success: bool) -> None:
            try:
                harness = request.app.state.harness
                if harness is None or not harness.learning_enabled:
                    return
                harness.learning_gate.record(
                    {
                        "task_type": "chat",
                        "complexity": "standard",
                        "description": "chat turn"},
                    {"success": success, "inference_attempted": True},
                    model_used=model_id or sessions.active_model or "unknown",
                    success=success,
                )
            except Exception as exc:
                logger.warning("learning record skipped: %s", exc)

        async def _log_run_cancelled(run_cancelled: object) -> None:
            # Fired when a client stop/disconnect cancels the run, so
            # the "Stop" button is observable server-side.
            logger.info("chat run cancelled: %s", run_cancelled)

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
                await session_store.record_turn(
                    store, session_id, result.all_messages()
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
                        # Decomposed from the stored Conversation: the
                        # UI adapter takes history/id/usage separately
                        # rather than the Conversation object itself.
                        conversation_id=(
                            session_id
                            or getattr(conversation, "conversation_id", None)
                        ),
                        usage=getattr(conversation, "usage", None),
                        on_complete=_save_turn,
                        on_cancel=_log_run_cancelled,
                    )
                except UnexpectedModelBehavior as exc:
                    if "ended without content" not in str(exc):
                        raise
                    if attempt == _MAX_EMPTY_STREAM_ATTEMPTS:
                        logger.exception(
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
            logger.exception("chat model request failed: %s", exc)
            _record_chat_outcome(success=False)
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
        from berg_agents.plugin_system.chat_integration import list_chat_plugins

        return {"plugins": await list_chat_plugins()}

    @router.post("/api/plugins/{plugin_id}/tools/{tool_name}")
    async def run_plugin_tool(
        plugin_id: str,
        tool_name: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a loaded plugin's tool by name (generic, plugin-agnostic).

        Plugin UIs call this instead of any todo-specific endpoint: the
        plugin's own callable runs with the project's `.berg-agents` in
        scope, so the tool's `todo_path`-style defaults resolve to the
        plugin's configured store.

        :param plugin_id: Plugin identifier.
        :param tool_name: Tool name the plugin declares.
        :param body: Keyword arguments for the tool.
        :return: Dict with ``result`` (string) or ``error``.
        :raises HTTPException: 404 for unknown plugin/tool, 502 when the
            tool raises.
        """
        args = {
            k: v
            for k, v in (body or {}).items()
            if k not in {"sessionId", "tool", "args"}
        }
        root_dir = sessions._harness_root_dir()
        # NOTE: run with the plugin config dir as cwd so relative
        # defaults in the tool signature land inside the project.
        import os

        had_cwd = pathlib.Path.cwd()
        os.chdir(root_dir)
        try:
            result = await _run_plugin_tool(
                plugin_id, tool_name, args, root_dir
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning(
                "Plugin tool %s/%s failed: %s", plugin_id, tool_name, exc
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            os.chdir(had_cwd)
        # Tools return human-readable strings for the model; a UI wants
        # structured data, so non-string returns are passed through as
        # JSON the caller can parse.
        if isinstance(result, str):
            return {"plugin": plugin_id, "tool": tool_name, "result": result}
        try:
            encoded = json.dumps(result, default=str)
        except (TypeError, ValueError):
            encoded = json.dumps({"value": str(result)})
        return {"plugin": plugin_id, "tool": tool_name, "result": encoded}

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

        state = await set_plugin_enabled(plugin_id, enabled=True)
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

        state = await set_plugin_enabled(plugin_id, enabled=False)
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
        from berg_agents.ui import session_store
        from pydantic_ai.ui.vercel_ai import VercelAIAdapter

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
        from berg_agents.ui import session_store
        from pydantic_ai_harness.step_persistence.conversations import (
            ConversationConflict,
        )

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
        # Offload the blocking resolve off the event loop (async handlers
        # should not do blocking pathlib work directly).
        root = await asyncio.to_thread(
            lambda: Path(sessions._harness_root_dir()).expanduser().resolve()
        )

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

    @router.get("/api/context/shared")
    async def shared_context_catalog() -> dict[str, Any]:
        """Catalog of the human-owned Shared Context for the in-app editor.

        :return: Dict with ``scopes`` (global/project -> path), per-section
            content presence, and recent journal history.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        ctx = SharedContext.resolve(sessions._harness_root_dir())
        return {
            "scopes": ctx.scopes(),
            "sections": [
                {
                    "name": name,
                    "has_content": bool(ctx.read(name).strip()),
                    "by_scope": {
                        layer.scope: bool(layer.read(name).strip())
                        for layer in ctx.layers
                    }}
                for name in SECTIONS
            ],
            "history": ctx.history()[:25]}

    @router.get("/api/context/shared/{section}")
    async def shared_context_section(section: str) -> dict[str, Any]:
        """Read one Shared Context section (project shadows global).

        :param section: Section name (an entry of ``SECTIONS``).
        :return: Effective content, scopes, and this section's history.
        :raises HTTPException: 404 for an unknown section.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        if section not in SECTIONS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}.",
            )
        ctx = SharedContext.resolve(sessions._harness_root_dir())
        return {
            "section": section,
            "content": ctx.read(section),
            "scopes": ctx.scopes(),
            "history": ctx.history(section)[:25]}

    @router.put("/api/context/shared/{section}")
    async def shared_context_write(
        section: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Write/append a section from the in-app editor (author ``human:ui``).

        Sections are validated against ``SECTIONS`` so only known context
        files are writable — no arbitrary paths (workspace files ride the
        one shared file-access path, added with E2).

        :param section: Section name.
        :param body: ``content`` (required), optional ``mode``
            ("write"/"append"), ``scope`` ("project"/"global"), ``why``.
        :return: The stored result and effective content.
        :raises HTTPException: 404 unknown section, 422 bad body.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        if section not in SECTIONS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}.",
            )
        content = body.get("content")
        if not isinstance(content, str):
            raise HTTPException(
                status_code=422, detail="Body needs a string 'content'."
            )
        mode = str(body.get("mode") or "write")
        scope = str(body.get("scope") or "project")
        why = str(body.get("why") or "")
        ctx = SharedContext.resolve(sessions._harness_root_dir())
        if mode == "append":
            changed = ctx.append(
                section, content, author="human:ui", why=why, scope=scope
            )
        else:
            changed = ctx.write(
                section, content, author="human:ui", why=why, scope=scope
            )
        return {
            "section": section,
            "changed": changed,
            "mode": mode,
            "scope": scope,
            "content": ctx.read(section)}

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

    register_provider_routes(router, sessions, providers)
    return router
