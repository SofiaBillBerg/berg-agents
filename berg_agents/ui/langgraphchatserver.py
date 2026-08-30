"""LangGraph-backed ChatServer implementation.

NOTE, this module is to be deprecated, bergagents server is independent of langchain.
The full migration is in progress. Below text is should be removed as soon as approprite:

    This is the *reference implementation* of the
    :class:`berg_agents.core.chat_server.ChatServer` protocol.  It owns all the
    mutable state (agent singletons, HITL events, cancel tasks, audit logs,
    protocol-v2 event queues) and every piece of business logic that today lives
    scattered across ``web.py``'s module-level globals.

    Design boundary:

    * ``langgraphchatserver.py`` handles **domain logic** - agent lifecycle, model
    switching, HITL interrupt handling, event queuing, audit, thread history.
    * ``web.py`` handles **HTTP concerns** - request parsing, response
    serialization, SSE framing (``data: `` prefix, event-id headers), and
    FastAPI middleware.

    The two files share no mutable state: ``web.py`` instantiates a single
    ``LangGraphChatServer`` at startup and every route handler calls into it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import datetime
import logging
from pathlib import Path
from typing import Any
import uuid

from berg_agents.agents.codeagent import build_agent, create_default_tools
from berg_agents.capabilities.envelope import InvocationRequest
from berg_agents.capabilities.registry import CapabilityRegistry
from berg_agents.config.settings import get_settings
from berg_agents.main import create_llm, load_config
from berg_agents.providers.registry import build_llm, resolve_model
from berg_agents.providers.registry import list_models as registry_list_models
from berg_agents.ui.protocol import translate_resume, translate_stream
from berg_agents.utils.checkpointer import build_checkpointer
from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage
from langchain.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types (keep in sync with web.py's Pydantic models)
# ---------------------------------------------------------------------------


class AgentState:
    """Runtime state of a LangGraph agent instance.

    Re-exported as a public name for backwards compatibility with tests.
    """

    __slots__ = ("agent", "checkpointer", "model", "provider", "thread_id")

    def __init__(
        self,
        agent: Any,
        thread_id: str,
        checkpointer: Any,
        provider: str = "ollama",
        model: str = "gpt-oss:20b",
    ) -> None:
        self.agent = agent
        self.thread_id = thread_id
        self.checkpointer = checkpointer
        self.provider = provider
        self.model = model


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------


class LangGraphChatServer:  # ruff: ignore[too-many-public-methods]
    """LangGraph-backed :class:`ChatServer` implementation.

    Every mutable piece of state that ``web.py`` used to keep as a module-
    level global is now an instance attribute of this class.  The singleton
    pattern (``_server`` at module level) means ``web.py`` creates one
    instance and all route handlers call into it.
    """

    def __init__(self) -> None:
        # -- agent state --------------------------------------------------
        self._state: AgentState | None = None
        self._thread_agents: dict[str, AgentState] = {}

        # -- capability registry ------------------------------------------
        self._registry: CapabilityRegistry | None = None

        # -- HITL (human-in-the-loop) ------------------------------------
        self._pending_hitl: dict[str, asyncio.Event] = {}
        self._hitl_decisions: dict[str, str] = {}
        self._hitl_payloads: dict[str, Any] = {}
        self._pending_interrupt_ids: dict[str, str] = {}

        # -- provider switching -------------------------------------------
        self._provider_switch_lock: asyncio.Lock = asyncio.Lock()
        self._switching: bool = False

        # -- cancel / task tracking ---------------------------------------
        self._pending_cancel: dict[str, asyncio.Event] = {}
        self._thread_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]

        # -- audit --------------------------------------------------------
        self._audit_log: dict[str, list[dict[str, Any]]] = {}
        self._audit_store: list[dict[str, Any]] = []

        # -- protocol v2 event queues ------------------------------------
        self._protocol_event_queues: dict[
            str, list[tuple[int, dict[str, Any]]]
        ] = {}
        self._protocol_stream_notifiers: dict[str, asyncio.Event] = {}
        self._protocol_stream_tasks: dict[str, set[asyncio.Task]] = {}  # type: ignore[type-arg]

    # ====================================================================
    # Agent lifecycle helpers
    # ====================================================================

    def _build_llm_for_model(
        self,
        provider: str,
        model: str,
        base_url: str | None,
        cfg: dict[str, Any],
    ) -> BaseChatModel:
        """Build a concrete BaseChatModel for a given model id."""
        resolved = resolve_model(model, cfg)
        if base_url:
            resolved["base_url"] = base_url
        return build_llm(resolved)

    def _get_or_create_agent_sync(
        self, thread_id: str | None = None
    ) -> AgentState:
        """Return agent state, building it lazily (sync, for startup)."""
        if thread_id and thread_id in self._thread_agents:
            return self._thread_agents[thread_id]
        if self._state is None:
            from berg_agents.cli import _load_mcp_tools
            from berg_agents.profiles.router import filter_tools_by_exclusions

            cfg = load_config()
            llm: BaseChatModel = create_llm(cfg)
            tools: list[BaseTool] = create_default_tools(
                root_dir=str(Path.cwd()), llm=llm
            )
            tools.extend(_load_mcp_tools(cfg))
            default_model = resolve_model(
                cfg.get("default_model") or None, cfg
            )["model"]
            tools = filter_tools_by_exclusions(tools, default_model)
            checkpointer = build_checkpointer(
                checkpoint_dir=get_settings().checkpoint_dir or None
            )
            agent = build_agent(llm=llm, tools=tools, checkpointer=checkpointer)
            self._state = AgentState(
                agent=agent,
                thread_id=str(uuid.uuid4()),
                checkpointer=checkpointer,
                provider=cfg.get("provider", "ollama"),
                model=cfg.get("model", "gpt-oss:20b"),
            )
        return self._state

    async def _get_or_create_agent_async(
        self, thread_id: str | None = None
    ) -> AgentState:
        """Return agent state, building it lazily (async, for request handlers)."""
        if thread_id and thread_id in self._thread_agents:
            return self._thread_agents[thread_id]
        if self._state is None:
            from berg_agents.cli import _load_mcp_tools_async
            from berg_agents.profiles.router import filter_tools_by_exclusions

            cfg = load_config()
            llm: BaseChatModel = create_llm(cfg)
            tools: list[BaseTool] = create_default_tools(
                root_dir=str(Path.cwd()), llm=llm
            )
            tools.extend(await _load_mcp_tools_async(cfg))
            default_model = resolve_model(
                cfg.get("default_model") or None, cfg
            )["model"]
            tools = filter_tools_by_exclusions(tools, default_model)
            checkpointer = build_checkpointer(
                checkpoint_dir=get_settings().checkpoint_dir or None
            )
            agent = build_agent(llm=llm, tools=tools, checkpointer=checkpointer)
            self._state = AgentState(
                agent=agent,
                thread_id=str(uuid.uuid4()),
                checkpointer=checkpointer,
                provider=cfg.get("provider", "ollama"),
                model=cfg.get("model", "gpt-oss:20b"),
            )
        return self._state

    async def _reinit_agent(self, provider: str, model: str) -> None:
        """Reinitialize the global agent with a new provider/model."""
        async with self._provider_switch_lock:
            self._switching = True
            try:
                cfg = load_config()
                cfg["provider"] = provider
                cfg["model"] = model
                llm = create_llm(cfg)
                tools = create_default_tools(root_dir=str(Path.cwd()), llm=llm)
                from berg_agents.cli import _load_mcp_tools

                tools.extend(_load_mcp_tools(cfg))
                checkpointer = None
                if self._state is not None:
                    checkpointer = self._state.checkpointer
                if checkpointer is None:
                    checkpointer = build_checkpointer(
                        checkpoint_dir=get_settings().checkpoint_dir
                    )
                if (
                    isinstance(checkpointer, (SqliteSaver, AsyncSqliteSaver))
                    and cfg.get("checkpoint_dir") is None
                ):
                    checkpointer = InMemorySaver()
                if isinstance(checkpointer, InMemorySaver) and cfg.get(
                    "checkpoint_dir"
                ):
                    checkpointer = build_checkpointer(
                        checkpoint_dir=cfg["checkpoint_dir"]
                    )
                agent = build_agent(
                    llm=llm, tools=tools, checkpointer=checkpointer
                )
                self._state = AgentState(
                    agent=agent,
                    thread_id=str(uuid.uuid4()),
                    checkpointer=checkpointer,
                    provider=provider,
                    model=model,
                )
            finally:
                self._switching = False

    # ====================================================================
    # Protocol v2 event queue helpers
    # ====================================================================

    def _get_or_create_queue(
        self, thread_id: str
    ) -> list[tuple[int, dict[str, Any]]]:
        """Get or create the event queue for a thread."""
        if thread_id not in self._protocol_event_queues:
            self._protocol_event_queues[thread_id] = []
        return self._protocol_event_queues[thread_id]

    def _get_or_create_notifier(self, thread_id: str) -> asyncio.Event:
        """Get or create the notifier event for a thread."""
        if thread_id not in self._protocol_stream_notifiers:
            self._protocol_stream_notifiers[thread_id] = asyncio.Event()
        return self._protocol_stream_notifiers[thread_id]

    def _push_protocol_event(
        self, thread_id: str, event: dict[str, Any]
    ) -> None:
        """Push a protocol event to the thread's queue and notify listeners."""
        queue = self._get_or_create_queue(thread_id)
        notifier = self._get_or_create_notifier(thread_id)
        seq = len(queue) + 1
        queue.append((seq, event))
        # Track interrupt IDs for input.respond matching
        if event.get("method") == "input":
            params = event.get("params", {})
            data = params.get("data", {})
            if data.get("event") == "input-requested":
                interrupt_id = data.get("id")
                if interrupt_id:
                    self._pending_interrupt_ids[thread_id] = interrupt_id
                self._hitl_payloads[thread_id] = data.get("value")
        notifier.set()

    @staticmethod
    def _extract_decision(response: Any) -> str:
        """Extract approve/reject decision from a resume response."""
        if isinstance(response, dict):
            decisions = response.get("decisions")
            if isinstance(decisions, list) and decisions:
                first = decisions[0]
                if isinstance(first, dict):
                    return (
                        "approve"
                        if first.get("type") == "approve"
                        else "reject"
                    )
            if "type" in response:
                return (
                    "approve" if response.get("type") == "approve" else "reject"
                )
            if "approved" in response:
                return "approve" if response.get("approved") else "reject"
        return "approve" if response else "reject"

    @staticmethod
    def _interrupt_action_count(value: Any) -> int:
        """Best-effort count of interrupts represented by a stored payload."""
        if isinstance(value, dict):
            requests = value.get("action_requests")
            if isinstance(requests, list) and requests:
                return len(requests)
            return 1
        if isinstance(value, list | tuple) and value:
            return len(value)
        return 1

    @staticmethod
    def _build_resume_value(
        response: Any, expected_count: int | None = None
    ) -> dict[str, Any]:
        """Normalize an input.respond payload into a LangChain HITL response."""
        decisions: list[Any] | None = None
        if isinstance(response, dict):
            raw = response.get("decisions")
            if (
                isinstance(raw, list)
                and raw
                and all(isinstance(d, dict) and "type" in d for d in raw)
            ):
                decisions = list(raw)
            elif "type" in response:
                decisions = [response]
            elif "approved" in response:
                decisions = [
                    {"type": "approve"}
                    if response["approved"]
                    else {"type": "reject"}
                ]
        if decisions is None:
            decisions = [{"type": "approve" if response else "reject"}]
        if expected_count and len(decisions) < expected_count:
            decisions += [decisions[-1]] * (expected_count - len(decisions))
        return {"decisions": decisions}

    async def _register_pending_hitl(self, thread_id: str) -> None:
        """Mark thread_id as paused-on-interrupt when its latest state says so."""
        try:
            state = await self._get_or_create_agent_async()
            snapshot = await state.agent.aget_state({
                "configurable": {"thread_id": thread_id}
            })
        except Exception as exc:  # pragma: no cover - defensive probe
            logger.warning("HITL state probe failed for %s: %s", thread_id, exc)
            return
        if (
            getattr(snapshot, "next", None)
            and thread_id not in self._pending_hitl
        ):
            self._pending_hitl[thread_id] = asyncio.Event()

    async def _resume_run(
        self, thread_id: str, resume_value: dict[str, Any]
    ) -> None:
        """Resume a paused run and stream continuation events into its queue."""
        try:
            print(f"[DEBUG] Resuming thread {thread_id} with {resume_value}")
            state = await self._get_or_create_agent_async()
            async for event in translate_resume(
                state.agent, resume_value, thread_id
            ):
                _evt_data = event.get("params", {}).get("data", {})
                print(
                    f"[DEBUG] Resume event: {event.get('method')} "
                    f"{_evt_data.get('event', '')}"
                )
                self._push_protocol_event(thread_id, event)
            await self._register_pending_hitl(thread_id)
            print(f"[DEBUG] Resume stream completed for thread {thread_id}")
        except asyncio.CancelledError:
            print(f"[DEBUG] Resume cancelled for thread {thread_id}")
        except Exception as exc:
            print(f"[DEBUG] Resume error for thread {thread_id}: {exc}")
            self._push_protocol_event(
                thread_id,
                {
                    "method": "lifecycle",
                    "params": {
                        "namespace": [],
                        "data": {"event": "failed", "error": str(exc)},
                    },
                },
            )

    # ====================================================================
    # Provider / model metadata
    # ====================================================================

    def list_providers(self) -> list[dict[str, Any]]:
        """Return all configured providers."""
        settings = get_settings()
        raw_list = settings.provider_list or []
        return [{"name": p["name"], "model": p["model"]} for p in raw_list]

    def get_active_provider(self) -> dict[str, Any]:
        """Return the currently active provider and model."""
        if self._state is not None:
            return {
                "provider": self._state.provider,
                "model": self._state.model,
            }
        settings = get_settings()
        return {
            "provider": settings.provider,
            "model": (
                settings.ollama_model
                if settings.provider == "ollama"
                else settings.openai_model
            ),
        }

    def validate_provider(
        self, provider: str, model: str
    ) -> dict[str, str] | None:
        """Validate provider/model against configured list. Returns error or None."""
        settings = get_settings()
        valid = {
            (p["name"], p["model"]) for p in (settings.provider_list or [])
        }
        if (provider, model) not in valid:
            return (
                f"Provider {provider!r} / model {model!r} "
                f"is not in the configured provider_list. "
                f"Valid combinations: {sorted(valid)}"
            )
        return None

    async def set_active_provider(
        self, provider: str, model: str
    ) -> dict[str, str]:
        """Switch the active provider/model (async, non-blocking)."""
        if (
            self._switching
            and self._state is not None
            and self._state.provider == provider
            and self._state.model == model
        ):
            return {"status": "ok"}
        if self._switching:
            return {"status": "error", "detail": "switch in progress"}
        asyncio.create_task(self._reinit_agent(provider, model))
        return {"status": "ok"}

    def is_switching(self) -> bool:
        """Return True if a provider switch is in progress."""
        return self._switching

    def list_models(self) -> list[dict[str, Any]]:
        """Return available models for the dynamic model selector."""
        cfg = load_config()
        models = registry_list_models(cfg)
        try:
            default = resolve_model(cfg.get("default_model") or None, cfg)
            default_id = default["model"]
        except KeyError:
            default_id = None
        for entry in models:
            entry["is_active"] = entry["model"] == default_id
        return models

    def list_capabilities(self) -> list[dict[str, Any]]:
        """Return metadata for every registered capability."""
        return self._get_registry().discover()

    def _get_registry(self) -> CapabilityRegistry:
        """Return the shared capability registry, building lazily."""
        if self._registry is None:
            from berg_agents.cli import _build_registry

            self._registry = _build_registry()
        return self._registry

    # ====================================================================
    # Threads
    # ====================================================================

    @staticmethod
    def create_thread(
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> dict[str, Any]:
        """Create a new thread."""
        tid = thread_id or uuid.uuid4().hex
        now = datetime.datetime.now(datetime.UTC).isoformat()
        return {
            "thread_id": tid,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
            "values": {},
        }

    async def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Get the current state of a thread."""
        state = await self._get_or_create_agent_async()
        checkpointer = getattr(state.agent, "checkpointer", None)
        if checkpointer is None:
            return {"values": {}, "next": [], "tasks": []}
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state_data = await checkpointer.aget(config)
            if not state_data:
                return {"values": {}, "next": [], "tasks": []}
            messages = state_data.get("messages", [])
            values = {k: v for k, v in state_data.items() if k != "messages"}
            return {
                "values": values,
                "messages": [
                    msg.to_dict() if hasattr(msg, "to_dict") else str(msg)
                    for msg in messages
                ],
                "next": [],
                "tasks": [],
            }
        except Exception as e:
            logger.exception("Error fetching thread state: %s", e)
            return {"values": {}, "next": [], "tasks": []}

    async def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Get past states for a thread."""
        state = await self._get_or_create_agent_async()
        checkpointer = getattr(state.agent, "checkpointer", None)
        if checkpointer is None:
            return []
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state_data = await checkpointer.aget(config)
            if not state_data:
                return []
            messages = state_data.get("messages", [])
            values = {k: v for k, v in state_data.items() if k != "messages"}
            return [
                {
                    "values": values,
                    "messages": [
                        msg.to_dict() if hasattr(msg, "to_dict") else str(msg)
                        for msg in messages
                    ],
                    "next": [],
                    "tasks": [],
                }
            ]
        except Exception as e:
            logger.exception("Error fetching thread history: %s", e)
            return []

    async def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Switch the model for a given thread."""
        from berg_agents.agents.codeagent import build_agent as _build_agent
        from berg_agents.cli import _load_mcp_tools_async
        from berg_agents.profiles.router import filter_tools_by_exclusions

        if (
            thread_id in self._thread_tasks
            and not self._thread_tasks[thread_id].done()
        ):
            return {
                "status": "error",
                "detail": (
                    "Cannot switch model while a run is active on this thread. "
                    "Wait for it to finish or cancel the run first."
                ),
            }

        cfg = load_config()
        llm = self._build_llm_for_model(provider, model, base_url, cfg)
        tools = create_default_tools(root_dir=str(Path.cwd()), llm=llm)
        tools.extend(await _load_mcp_tools_async(cfg))
        tools = filter_tools_by_exclusions(tools, model)

        existing = self._thread_agents.get(thread_id)
        if existing:
            checkpointer = existing.checkpointer
        elif self._state:
            checkpointer = self._state.checkpointer
        else:
            checkpointer = build_checkpointer(
                checkpoint_dir=get_settings().checkpoint_dir or None
            )

        agent = _build_agent(llm=llm, tools=tools, checkpointer=checkpointer)
        self._thread_agents[thread_id] = AgentState(
            agent=agent,
            thread_id=thread_id,
            checkpointer=checkpointer,
            provider=provider,
            model=model,
        )
        return {
            "status": "success",
            "thread_id": thread_id,
            "provider": provider,
            "model": model,
            "message": f"Switched to {provider}:{model}",
        }

    async def export_thread(self, thread_id: str, format: str = "md") -> str:
        """Export a thread's conversation as markdown."""
        if format != "md":
            raise ValueError("Unsupported format")

        clean_id = (
            thread_id.split(".", maxsplit=1)[0][:12]
            if "." in thread_id
            else thread_id[:12]
        )

        state = await self._get_or_create_agent_async(thread_id)
        checkpointer = getattr(state.agent, "checkpointer", None)
        lines: list[str] = ["# CodeAgent chat export", ""]
        lines.extend((f"**Thread ID:** `{clean_id}`", ""))

        if checkpointer is not None:
            try:
                config = {"configurable": {"thread_id": thread_id}}
                messages: list = []
                todos: list = []
                debug_data = None

                # 1. Try StateSnapshot via agent.aget_state (handles both backends)
                try:
                    snapshot = await state.agent.aget_state(config)  # type: ignore[attr-defined]
                    if snapshot is not None and hasattr(snapshot, "values"):
                        vals = getattr(snapshot, "values", {}) or {}
                        if isinstance(vals, dict):
                            messages = vals.get("messages", []) or []
                            todos = vals.get("todos", []) or []
                            debug_data = vals
                except Exception:
                    pass

                # 2. Fallback to raw checkpointer
                if not messages:
                    try:
                        data = await checkpointer.aget(config)
                        debug_data = data
                        if isinstance(data, dict):
                            cv = (
                                data.get("channel_values")
                                if isinstance(data.get("channel_values"), dict)
                                else None
                            )
                            if cv and cv.get("messages"):
                                messages = cv.get("messages", []) or []
                                todos = cv.get("todos", todos) or []
                            elif data.get("messages"):
                                messages = data.get("messages", []) or []
                                todos = data.get("todos", todos) or []
                            else:
                                for alt in [
                                    data.get("values"),
                                    data.get("checkpoint"),
                                    cv,
                                ]:
                                    if isinstance(alt, dict) and alt.get(
                                        "messages"
                                    ):
                                        messages = alt.get("messages", []) or []
                                        if not todos and alt.get("todos"):
                                            todos = alt.get("todos", []) or []
                                        break
                    except Exception as e:
                        logger.debug("checkpointer fallback failed: %s", e)

                if not messages:
                    if debug_data is None:
                        lines.append(
                            "*[No conversation data found for this thread]*"
                        )
                    else:
                        lines.extend(("*[No messages in conversation]*", ""))
                        lines.append(
                            f"**Debug data keys:** {', '.join(debug_data.keys())}"
                        )
                        cv = debug_data.get("channel_values")
                        if isinstance(cv, dict):
                            lines.append(
                                "**Channel values keys:** "
                                + ", ".join(cv.keys())
                            )
                            if cv.get("messages") is not None:
                                lines.append(
                                    f"**Messages channel_values:** {len(cv.get('messages', []))}"
                                )
                            if debug_data.get("messages") is not None:
                                lines.append(
                                    f"**Messages top-level:** {len(debug_data.get('messages', []))}"
                                )
                else:
                    for msg in messages:
                        mtype = getattr(msg, "type", "") or (
                            msg.get("type", "") if isinstance(msg, dict) else ""
                        )
                        content = getattr(msg, "content", "") or (
                            msg.get("content", "")
                            if isinstance(msg, dict)
                            else ""
                        )
                        if isinstance(content, list):
                            content = "\n".join(
                                b.get("text", "")
                                if isinstance(b, dict)
                                else str(b)
                                for b in content
                            )
                        content = (content or "").strip()
                        if mtype == "tool":
                            name = getattr(msg, "name", "tool") or (
                                msg.get("name", "tool")
                                if isinstance(msg, dict)
                                else "tool"
                            )
                            lines.append(f"**🔧 {name}**")
                            lines.append("")
                            lines.append("```")
                            lines.append(content[:500])
                            lines.append("```")
                        elif mtype == "human":
                            lines.append(f"**You:**\n\n{content}")
                        elif mtype == "ai":
                            calls = (
                                getattr(msg, "tool_calls", None)
                                or (
                                    msg.get("tool_calls", [])
                                    if isinstance(msg, dict)
                                    else []
                                )
                                or []
                            )
                            for tc in calls:
                                args = (
                                    tc.get("args", {})
                                    if isinstance(tc, dict)
                                    else {}
                                )
                                target = (
                                    args.get("file_path")
                                    or args.get("path")
                                    or args.get("pattern")
                                    or ""
                                )
                                lines.append(
                                    f"*→ {tc.get('name', 'tool') if isinstance(tc, dict) else 'tool'} {target}*"
                                )
                            if content:
                                lines.append(f"**Agent:**\n\n{content}")
                        else:
                            lines.append(f"**{mtype}:** {content}")
                        lines.append("")

                    if todos:
                        lines.append("## Todo list at end of run")
                        lines.append("")
                        for t in todos:
                            mark = (
                                "x"
                                if (
                                    t.get("status") == "completed"
                                    if isinstance(t, dict)
                                    else getattr(t, "status", None)
                                    == "completed"
                                )
                                else " "
                            )
                            content = (
                                t.get("content", "")
                                if isinstance(t, dict)
                                else getattr(t, "content", "")
                            )
                            lines.append(f"- [{mark}] {content}")
            except Exception as e:
                logger.exception("Error exporting thread %s: %s", thread_id, e)
                lines.append(f"*[export error: {e}]*")
        else:
            lines.append("*[no checkpointer - nothing to export]*")

        return "\n".join(lines)

    # ====================================================================
    # Runs / streaming (background task + event queue)
    # ====================================================================

    def start_background_run(
        self,
        thread_id: str,
        text: str,
        *,
        run_id: str | None = None,
    ) -> str:
        """Start a background agent run, push events to the queue.

        Returns the run_id (for the Content-Location header).
        """
        rid = run_id or str(uuid.uuid4())
        effective_thread = thread_id

        async def _run() -> None:
            try:
                print(
                    f"[DEBUG] Starting stream for thread {effective_thread}, "
                    f"text: {text[:50]}"
                )
                state = await self._get_or_create_agent_async()
                delta_count = 0
                async for event in translate_stream(
                    state.agent, text, effective_thread
                ):
                    evt_method = event.get("method", "")
                    _evt_data = event.get("params", {}).get("data", {})
                    if evt_method == "messages" and _evt_data.get("event") in (
                        "content-block-delta",
                        "message-start",
                        "message-finish",
                    ):
                        self._push_protocol_event(effective_thread, event)
                        if _evt_data.get("event") == "content-block-delta":
                            delta_count += 1
                            continue
                        print(
                            f"[DEBUG] Pushing event: messages "
                            f"{_evt_data.get('event')}"
                        )
                    else:
                        print(
                            f"[DEBUG] Pushing event: {evt_method} "
                            f"{_evt_data.get('event', '')}"
                            + (
                                f" | error: {_evt_data.get('error')}"
                                if _evt_data.get("error")
                                else ""
                            )
                        )
                    self._push_protocol_event(effective_thread, event)
                if delta_count:
                    print(
                        f"[DEBUG] ({delta_count} streaming deltas suppressed)"
                    )
                print(
                    f"[DEBUG] TERMINAL: stream loop ended for thread "
                    f"{effective_thread}"
                )
                await self._register_pending_hitl(effective_thread)
            except asyncio.CancelledError:
                print(f"[DEBUG] Stream cancelled for thread {effective_thread}")
            except Exception as exc:
                print(
                    f"[DEBUG] Stream error for thread {effective_thread}: {exc}"
                )
                self._push_protocol_event(
                    effective_thread,
                    {
                        "method": "lifecycle",
                        "params": {
                            "namespace": [],
                            "data": {"event": "failed", "error": str(exc)},
                        },
                    },
                )

        task = asyncio.create_task(_run())
        self._thread_tasks[effective_thread] = task
        return rid

    def check_concurrency(self, thread_id: str) -> str | None:
        """Return an error message if a run is already active, else None."""
        existing = self._thread_tasks.get(thread_id)
        if existing is not None and not existing.done():
            return (
                "A run is already active on this thread. Wait for it to "
                "finish or cancel it before sending a new message."
            )
        return None

    async def handle_protocol_command(
        self,
        thread_id: str,
        method: str,
        params: dict[str, Any],
        command_id: int = 0,
    ) -> dict[str, Any]:
        """Handle a LangGraph protocol v2 command (run.start, input.respond, run.stop)."""

        def _ok(result: dict[str, Any] | None = None) -> dict[str, Any]:
            return {
                "type": "success",
                "id": command_id,
                "result": result or {},
            }

        if method == "run.start":
            input_data = params.get("input", {})
            messages = input_data.get("messages", [])
            human_msg = next(
                (m for m in messages if m.get("type") in ("human", "user")),
                None,
            )
            text = human_msg.get("content", "") if human_msg else ""
            if not text:
                return _ok()

            effective_thread = (
                thread_id or (await self._get_or_create_agent_async()).thread_id
            )

            err = self.check_concurrency(effective_thread)
            if err:
                from fastapi import HTTPException

                raise HTTPException(status_code=409, detail=err)

            run_id = self.start_background_run(effective_thread, text)
            return _ok({"run_id": run_id})

        elif method == "input.respond":
            response = params.get("response", {})
            interrupt_id = params.get("interrupt_id")

            if interrupt_id:
                expected_id = self._pending_interrupt_ids.get(thread_id)
                if expected_id and expected_id != interrupt_id:
                    return {"status": "error", "error": "interrupt_id mismatch"}

            if thread_id not in self._pending_hitl:
                await self._register_pending_hitl(thread_id)
            if thread_id not in self._pending_hitl:
                return {"status": "error", "error": "no pending interrupt"}

            payload_value = self._hitl_payloads.get(thread_id)
            resume_value = self._build_resume_value(
                response, self._interrupt_action_count(payload_value)
            )
            task = asyncio.create_task(
                self._resume_run(thread_id, resume_value)
            )
            self._thread_tasks[thread_id] = task

            self._pending_hitl.pop(thread_id, None)
            self._hitl_payloads.pop(thread_id, None)
            self._pending_interrupt_ids.pop(thread_id, None)
            return _ok()

        elif method == "run.stop":
            task = self._thread_tasks.get(thread_id)
            if task and not task.done():
                task.cancel()
            return _ok()

        return _ok()

    def cancel_run(self, thread_id: str) -> None:
        """Cancel the background task for a thread."""
        task = self._thread_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()

    # ====================================================================
    # Thread event streaming (protocol v2 SSE)
    # ====================================================================

    async def thread_stream_events(
        self, thread_id: str, since: int = 0
    ) -> AsyncGenerator[dict[str, Any]]:
        """Yield protocol v2 events from the queue (replay + live tail)."""
        queue = self._get_or_create_queue(thread_id)
        notifier = self._get_or_create_notifier(thread_id)
        _since = since
        try:
            for seq, event in queue:
                if seq > _since:
                    _since = seq
                    yield event
            while True:
                await notifier.wait()
                notifier.clear()
                for seq, event in queue:
                    if seq > _since:
                        _since = seq
                        yield event
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("protocol v2 event stream failed: %s", e)

    # ====================================================================
    # HITL (legacy /chat/resume)
    # ====================================================================

    def resume_hitl(self, thread_id: str, decision: str) -> None:
        """Deliver a HITL decision for a paused interrupt.

        Raises ValueError if no pending interrupt exists.
        """
        ev = self._pending_hitl.get(thread_id)
        if ev is None:
            raise ValueError(
                f"No pending HITL interrupt for thread_id={thread_id!r}"
            )
        self._hitl_decisions[thread_id] = decision
        ev.set()

    # ====================================================================
    # Cancel (legacy /chat/cancel)
    # ====================================================================

    def cancel_legacy(self, thread_id: str) -> None:
        """Cancel a running agent thread (legacy endpoint).

        Raises ValueError if no running task.
        """
        task = self._thread_tasks.get(thread_id)
        if task is None or task.done():
            raise ValueError(f"No running task for thread_id={thread_id!r}")
        task.cancel()

    # ====================================================================
    # Legacy "current chat" convenience methods
    # These delegate to thread-based implementations using the active thread.
    # ====================================================================

    def _active_thread_id(self) -> str:
        """Return the active thread id from the current state."""
        if self._state is not None:
            return self._state.thread_id
        return self._get_or_create_agent_sync().thread_id

    def chat(self, text: str, thread_id: str | None = None) -> dict[str, Any]:
        """Send a chat message synchronously (legacy endpoint)."""
        effective_thread = thread_id or self._active_thread_id()
        state = self._get_or_create_agent_sync(effective_thread)
        effective_thread = thread_id or state.thread_id
        result = state.agent.invoke(
            {"messages": [HumanMessage(content=text)]},
            config={
                "configurable": {"thread_id": effective_thread},
                "recursion_limit": 150,
            },
        )
        messages = result.get("messages", [])
        response_text = "(no text response)"
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                response_text = msg.content
                break
        return {"response": response_text, "thread_id": effective_thread}

    async def chat_stream(
        self, text: str, thread_id: str | None = None
    ) -> AsyncGenerator[str]:
        """Stream a chat response via SSE frames (legacy endpoint)."""
        settings = get_settings()
        if not settings.stream_enabled:
            raise RuntimeError("Streaming is disabled.")
        if self._switching:
            raise RuntimeError("provider switch in progress")

        state = await self._get_or_create_agent_async()
        effective_thread = thread_id or state.thread_id

        async def _inner() -> AsyncGenerator[str]:
            try:
                from berg_agents.ui.protocol import _sse

                async for event in translate_stream(
                    state.agent, text, effective_thread
                ):
                    yield _sse(event)
            finally:
                self._thread_tasks.pop(effective_thread, None)

        streamer = _inner()
        task = asyncio.create_task(streamer.__anext__())
        self._thread_tasks[effective_thread] = task

        async def _consume() -> AsyncGenerator[str]:
            try:
                async for chunk in streamer:
                    yield chunk
            except asyncio.CancelledError:
                pass
            finally:
                self._thread_tasks.pop(effective_thread, None)

        # Return the generator - web.py wraps it in StreamingResponse
        async for chunk in _consume():
            yield chunk

    async def chat_history(
        self, thread_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return message history for a thread (legacy endpoint)."""
        state = await self._get_or_create_agent_async()
        checkpointer = getattr(state.agent, "checkpointer", None)
        if checkpointer is None:
            return []
        try:
            config = {"configurable": {"thread_id": thread_id}}
            state_data = await checkpointer.aget(config)
            messages = state_data.get("messages", []) if state_data else []
            result = []
            for msg in messages[-limit:]:
                if hasattr(msg, "to_dict"):
                    result.append(msg.to_dict())
                elif hasattr(msg, "content"):
                    result.append({"role": "user", "content": msg.content})
                else:
                    result.append({"role": "user", "content": str(msg)})
            return result
        except Exception as e:
            logger.exception("Error fetching chat history: %s", e)
            return []

    def audit_entry(
        self,
        thread_id: str,
        action: str,
        details: str = "",
        timestamp: str = "",
        user: str = "",
    ) -> dict[str, Any]:
        """Record an audit log entry."""
        entry = {
            "thread_id": thread_id,
            "action": action,
            "details": details,
            "timestamp": timestamp,
            "user": user,
        }
        self._audit_store.append(entry)
        return {"status": "recorded"}

    def audit_list(self, thread_id: str) -> list[dict[str, Any]]:
        """List audit log entries for a thread."""
        return [e for e in self._audit_store if e.get("thread_id") == thread_id]

    # ====================================================================
    # Capabilities
    # ====================================================================

    def invoke_capability(
        self, capability_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a capability invocation."""
        request = InvocationRequest(
            request_id=uuid.uuid4().hex,
            capability_id=capability_id,
            params=params,
            caller="web",
        )
        response, receipt = self._get_registry().dispatch(request)
        if response.status == "error":
            raise ValueError(response.error)
        return {
            "response": response.model_dump(),
            "receipt": receipt.model_dump(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton - created once, used by web.py's route handlers.
# ---------------------------------------------------------------------------

_server: LangGraphChatServer | None = None


def get_server() -> LangGraphChatServer:
    """Return the singleton LangGraphChatServer instance."""
    global _server  # ruff: ignore[global-statement]
    if _server is None:
        _server = LangGraphChatServer()
    return _server
