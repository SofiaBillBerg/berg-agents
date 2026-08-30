"""LangChain/LangGraph adapter for berg_agents.

This module provides a framework adapter that wraps LangGraph/LangChain
as a backend for berg_agents. It is an *optional* dependency — berg_agents
works without LangChain installed (using native_adapter), but this adapter
enables the full DeepAgents harness when available.

The adapter follows the AbstractAgent interface so the orchestrator can
treat it like any other agent implementation.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.interface import AbstractAgent, AgentResult, TaskContext

logger = logging.getLogger(__name__)

# LangChain availability is determined at import time
_LANGCHAIN_AVAILABLE = False
try:
    import langchain  # ruff: ignore[unused-import]

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    pass


def is_langchain_available() -> bool:
    """Check if LangChain/LangGraph is installed.

    Returns:
        True if LangChain is importable.
    """
    return _LANGCHAIN_AVAILABLE


class LangChainAdapter:
    """Adapter that wraps LangGraph/LangChain as a backend.

    Provides a bridge between berg_agents' framework-agnostic interface
    and the LangGraph-based DeepAgents harness.

    Usage:
        adapter = LangChainAdapter(llm=some_chat_model)
        agent = adapter.create_agent(tools=[...], root_dir=".")
    """

    def __init__(
        self,
        llm: Any = None,
        *,
        checkpointer: Any = None,
        store: Any = None,
    ) -> None:
        """Initialize the LangChain adapter.

        Args:
            llm: A LangChain BaseChatModel instance.
            checkpointer: Optional LangGraph checkpointer for HITL.
            store: Optional LangGraph store for cross-thread memory.

        Raises:
            ImportError: If LangChain/LangGraph is not installed.
        """
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain/LangGraph is required for LangChainAdapter. "
                "Install with: uv add langchain langgraph deepagents"
            )
        self.llm = llm
        self.checkpointer = checkpointer
        self.store = store

    def create_agent(
        self,
        tools: list[Any] | None = None,
        *,
        root_dir: str = ".",
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create a LangGraph-based agent using the DeepAgents harness.

        Args:
            tools: Custom tools to add to the agent.
            root_dir: Working directory mounted at /workspace/.
            system_prompt: Optional system prompt override.
            **kwargs: Extra args forwarded to build_berg_agents.

        Returns:
            A compiled LangGraph state graph.
        """
        from berg_agents.agents.codeagent import build_berg_agents

        return build_berg_agents(
            llm=self.llm,
            tools=tools,
            root_dir=root_dir,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            store=self.store,
            **kwargs,
        )

    def create_native_agent(
        self,
        name: str,
        *,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
    ) -> LangGraphAgent:
        """Create a LangGraph-backed AbstractAgent.

        Args:
            name: Agent name.
            tools: Tools for the agent.
            system_prompt: System prompt.

        Returns:
            A LangGraphAgent wrapping the LangGraph harness.
        """
        return LangGraphAgent(
            name=name,
            llm=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
        )


class LangGraphAgent(AbstractAgent):
    """A LangGraph-based agent that implements AbstractAgent.

    Wraps a compiled LangGraph state graph and provides the standard
    AbstractAgent interface for use in the orchestrator.
    """

    def __init__(
        self,
        name: str,
        llm: Any = None,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
        checkpointer: Any = None,
    ) -> None:
        """Initialize the LangGraph agent.

        Args:
            name: Agent name.
            llm: LangChain chat model.
            tools: Tools for the agent.
            system_prompt: System prompt.
            checkpointer: Optional checkpointer for HITL.
        """
        self.name = name
        self.description = f"LangGraph agent: {name}"
        self.preferred_model_tier = "medium"
        self.capabilities = ["langgraph", "deepagents"]
        self._llm = llm
        self._tools = tools or []
        self._system_prompt = system_prompt
        self._checkpointer = checkpointer
        self._graph: Any = None

    def _ensure_graph(self) -> None:
        """Lazy-initialize the LangGraph graph."""
        if self._graph is None:
            adapter = LangChainAdapter(
                llm=self._llm,
                checkpointer=self._checkpointer,
            )
            self._graph = adapter.create_agent(
                tools=self._tools,
                system_prompt=self._system_prompt,
            )

    def can_handle(self, task: dict[str, Any]) -> float:
        """LangGraph agent can handle any task that has a description.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score (0.7 for most tasks).
        """
        if "description" in task:
            return 0.7
        return 0.1

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Execute the task via the LangGraph graph.

        Args:
            task: Task dictionary with at least 'description'.
            context: Task context.
            model: Optional model override.

        Returns:
            AgentResult with execution status.
        """
        self._ensure_graph()

        try:
            result = self._graph.invoke(
                {"messages": [("user", context.description)]},
                config={"configurable": {"thread_id": context.task_id}},
            )
            return AgentResult(
                success=True,
                output=result,
                model_used=getattr(self._llm, "model_name", None)
                if self._llm
                else None,
            )
        except Exception as e:
            logger.error("LangGraph agent execution failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )
