"""Orchestrator-based web server for berg_agents.

This is the NEW primary web server that uses the framework-agnostic
Orchestrator as the central coordinator. LangChain/LangGraph is used
only as an optional backend adapter for LLM execution.

Architecture:
    Web UI → OrchestratorServer → Orchestrator → Subagents (Guardian, Planner, etc.)
                                         ↓
                                   LangGraph Adapter (optional backend)

The existing LangGraphChatServer is kept for backwards compatibility
but new features should go through this orchestrator-based server.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import logging
from typing import Any
import uuid

from berg_agents.core.model_router import ModelRouter
from berg_agents.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class OrchestratorServer:
    """Web server that uses the Orchestrator as the primary interface.

    This server coordinates all subagents through the framework-agnostic
    orchestrator. It provides:
    - Agent discovery and info
    - Task execution with SSE streaming
    - Learning/outcome statistics
    - HITL (human-in-the-loop) support
    """

    def __init__(self, *, enable_learning: bool = True) -> None:
        """Initialize the orchestrator server.

        Args:
            enable_learning: Whether to enable the learning gate.
        """
        self.router = ModelRouter()
        self.orchestrator = Orchestrator(
            router=self.router,
            enable_learning=enable_learning,
        )

        # HITL state
        self._pending_hitl: dict[str, asyncio.Event] = {}
        self._hitl_decisions: dict[str, str] = {}

        # Event queues for SSE streaming
        self._event_queues: dict[str, list[dict[str, Any]]] = {}
        self._event_notifiers: dict[str, asyncio.Event] = {}

        # Thread tracking
        self._thread_tasks: dict[str, asyncio.Task] = {}

    # ====================================================================
    # Agent discovery
    # ====================================================================

    def list_agents(self) -> list[dict[str, Any]]:
        """Return info for all registered agents.

        Returns:
            List of agent info dicts with name, description, capabilities.
        """
        return self.orchestrator.get_agent_info()

    def get_agent(self, name: str) -> dict[str, Any]:
        """Get info for a specific agent.

        Args:
            name: Agent name.

        Returns:
            Agent info dict.

        Raises:
            KeyError: If agent not found.
        """
        agent = self.orchestrator.get_agent(name)
        return agent.get_info()

    # ====================================================================
    # Task execution
    # ====================================================================

    async def execute_task(
        self,
        description: str,
        *,
        task_type: str = "generic",
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a task through the orchestrator.

        This is the primary entry point for task execution. It runs the
        full workflow: complexity estimation → risk assessment → HITL →
        planning → execution → curation → learning.

        Args:
            description: Task description.
            task_type: Type of task (e.g. "edit_file", "refactor").
            task_id: Optional task ID (generated if not provided).
            metadata: Optional task metadata.

        Returns:
            Execution result dict with status, plan, and agent outputs.
        """
        task = {
            "description": description,
            "task_type": task_type,
            "metadata": metadata or {},
        }

        result = self.orchestrator.execute_task(task, task_id=task_id)

        # If HITL is needed, register the pending interrupt
        if result.get("status") == "needs_human_review":
            thread_id = result.get("task_id", "")
            self._pending_hitl[thread_id] = asyncio.Event()

        return result

    async def submit_task_stream(
        self,
        description: str,
        *,
        task_type: str = "generic",
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Submit a task for background execution with SSE streaming.

        Args:
            description: Task description.
            task_type: Type of task.
            thread_id: Optional thread ID.
            metadata: Optional task metadata.

        Returns:
            The thread ID for subscribing to events.
        """
        tid = thread_id or uuid.uuid4().hex

        async def _run() -> None:
            try:
                self._push_event(
                    tid,
                    {
                        "type": "task_started",
                        "data": {
                            "description": description,
                            "task_type": task_type,
                        },
                    },
                )

                result = await self.execute_task(
                    description,
                    task_type=task_type,
                    task_id=tid,
                    metadata=metadata,
                )

                if result.get("status") == "needs_human_review":
                    self._push_event(
                        tid,
                        {
                            "type": "hitl_requested",
                            "data": {
                                "reasons": result.get("review_reasons", []),
                                "risk_level": result.get("risk_level"),
                                "complexity": result.get("complexity"),
                            },
                        },
                    )
                else:
                    self._push_event(
                        tid,
                        {
                            "type": "task_completed",
                            "data": result,
                        },
                    )
            except Exception as e:
                self._push_event(
                    tid,
                    {
                        "type": "task_failed",
                        "data": {"error": str(e)},
                    },
                )

        task = asyncio.create_task(_run())
        self._thread_tasks[tid] = task
        return tid

    async def respond_to_hitl(
        self, thread_id: str, decision: str
    ) -> dict[str, Any]:
        """Respond to a HITL interrupt.

        Args:
            thread_id: Thread ID with pending HITL.
            decision: "approve" or "reject".

        Returns:
            Result of resuming the task.
        """
        if thread_id not in self._pending_hitl:
            return {"status": "error", "error": "no pending interrupt"}

        self._hitl_decisions[thread_id] = decision
        self._pending_hitl[thread_id].set()

        return {"status": "ok", "decision": decision}

    # ====================================================================
    # Learning stats
    # ====================================================================

    def get_learning_stats(self) -> dict[str, Any]:
        """Return learning/outcome statistics.

        Returns:
            Dict with outcome stats from the ModelRouter.
        """
        return self.orchestrator.get_learning_stats()

    # ====================================================================
    # SSE event streaming
    # ====================================================================

    def _push_event(self, thread_id: str, event: dict[str, Any]) -> None:
        """Push an event to a thread's queue."""
        if thread_id not in self._event_queues:
            self._event_queues[thread_id] = []
        self._event_queues[thread_id].append(event)

        notifier = self._event_notifiers.get(thread_id)
        if notifier:
            notifier.set()

    async def stream_events(
        self, thread_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for a thread via SSE.

        Args:
            thread_id: Thread ID to stream events for.

        Yields:
            Event dicts as they occur.
        """
        if thread_id not in self._event_queues:
            self._event_queues[thread_id] = []
        if thread_id not in self._event_notifiers:
            self._event_notifiers[thread_id] = asyncio.Event()

        queue = self._event_queues[thread_id]
        notifier = self._event_notifiers[thread_id]

        # Yield existing events
        for event in queue:
            yield event

        # Wait for new events
        while True:
            await notifier.wait()
            notifier.clear()
            for event in queue:
                yield event
            await asyncio.sleep(0.01)

    # ====================================================================
    # Thread management
    # ====================================================================

    def create_thread(self) -> str:
        """Create a new thread ID.

        Returns:
            New thread ID.
        """
        return uuid.uuid4().hex

    def cancel_task(self, thread_id: str) -> None:
        """Cancel a running task.

        Args:
            thread_id: Thread ID to cancel.
        """
        task = self._thread_tasks.get(thread_id)
        if task and not task.done():
            task.cancel()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_server: OrchestratorServer | None = None


def get_orchestrator_server() -> OrchestratorServer:
    """Return the singleton OrchestratorServer instance."""
    global _server  # ruff: ignore[global-statement]
    if _server is None:
        _server = OrchestratorServer()
    return _server
