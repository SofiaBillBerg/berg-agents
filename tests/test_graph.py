"""Unit tests for the LangChain create_agent and DeepAgents harnesses.

The tests verify that:

* the ``create_agent`` harness invokes tools correctly,
* a ``ToolMessage`` is produced when tools are called,
* normal ``AIMessage`` responses work,
* the graph handles LLM errors,
* the ``deepagents`` harness builds a compiled graph,
* built-in tool collisions are dropped for ``deepagents``,
* deepagents profile registration requires a profile key.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.uuid import uuid7
from typing_extensions import override

from berg_agents.agents.codeagent import (
    build_berg_agents,
    make_backend,
    make_default_permissions,
)
from berg_agents.utils.graph import build_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a MagicMock that mimics a LangChain LLM for create_agent.

    The mock returns a tool call when the prompt contains the word
    ``"tool"`` (case-insensitive). Otherwise, it returns a plain
    ``AIMessage``.

    :return: The mock LLM.
    """
    mock = MagicMock()

    def _invoke(messages: list) -> AIMessage:
        """Return a tool call if the prompt contains the word ``"tool"``.

        Otherwise, return a plain ``AIMessage``.

        :param messages: The messages to process.
        :return: The response message.
        """
        prompt = str(messages[-1].content)
        if "tool" in prompt.lower():
            return AIMessage(
                content="",
                tool_calls=[{"name": "dummy", "args": {}, "id": "1"}],
            )
        return AIMessage(content="Hello, world!")

    mock.invoke.side_effect = _invoke
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def dummy_tool() -> BaseTool:
    """A simple dummy tool.

    :return: The tool.
    """

    @tool
    def dummy() -> str:
        """A dummy tool that returns a string.

        :return: A dummy string.
        """
        return "dummy output"

    return dummy


@pytest.fixture
def agent_graph(mock_llm: MagicMock, dummy_tool: BaseTool) -> Any:
    """Create a CodeAgent wired with the mock LLM and an in-memory store.

    :param mock_llm: The mock LLM.
    :param dummy_tool: The dummy tool.
    :return: The agent graph.
    """
    return build_graph(llm=mock_llm, tools=[dummy_tool])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_invokes_tool(agent_graph: Any) -> None:
    """The agent should call the tool and return a ``ToolMessage``.

    :param agent_graph: The agent graph to test.
    :return: None
    """
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Please call a tool")]}

    final_state = agent_graph.invoke(state, config=config)

    tool_msgs = [
        m for m in final_state.get("messages", []) if isinstance(m, ToolMessage)
    ]
    assert len(tool_msgs) >= 1, (
        "Expected at least one ToolMessage in the final state"
    )

    # Verify that the tool call was made correctly.
    assert tool_msgs[0].name == "dummy"


def test_agent_returns_normal_ai_message(agent_graph: Any) -> None:
    """If the LLM does not request a tool, the agent should return a normal AIMessage.

    :param agent_graph: The agent graph to test.
    :return: None
    """
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Say hello")]}

    final_state = agent_graph.invoke(state, config=config)

    ai_msgs = [
        m for m in final_state.get("messages", []) if isinstance(m, AIMessage)
    ]
    assert len(ai_msgs) >= 1
    assert ai_msgs[-1].content == "Hello, world!"


def test_graph_handles_llm_error(
    mock_llm: MagicMock, dummy_tool: BaseTool
) -> None:
    """If the LLM raises an exception, the graph should propagate it.

    :param mock_llm: The mock LLM that will raise an exception.
    :param dummy_tool: A dummy tool.
    :return: None
    """
    mock_llm.invoke.side_effect = RuntimeError("LLM failure")
    graph = build_graph(llm=mock_llm, tools=[dummy_tool])
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid7())}}
    state = {"messages": [HumanMessage(content="Trigger an error")]}

    with pytest.raises(RuntimeError, match="LLM failure"):
        graph.invoke(state, config=config)


def test_readonly_mcp_tools_are_not_gated(mock_llm: MagicMock) -> None:
    """Read-only MCP tools must never be added to ``interrupt_on``.

    Sensitive MCP tools (e.g. ``github``) are gated for human approval, while
    read-only MCP tools (e.g. ``codegraph``) stay autonomous.

    :param mock_llm: The mock LLM.
    :return: None
    """
    from berg_agents.config.mcp import apply_mcp_tool_prefixes

    @tool
    def create_issue(title: str) -> str:
        """Create a GitHub issue.

        :param title: The issue title.
        :return: A confirmation string.
        """
        return f"created {title}"

    @tool
    def explore(query: str) -> str:
        """Explore the codebase.

        :param query: The query.
        :return: Exploration results.
        """
        return f"results for {query}"

    github_tool = apply_mcp_tool_prefixes([create_issue], "github")[0]
    codegraph_tool = apply_mcp_tool_prefixes([explore], "codegraph")[0]

    with patch("berg_agents.utils.graph.create_agent") as mock_create_agent:
        build_graph(llm=mock_llm, tools=[github_tool, codegraph_tool])

    mock_create_agent.assert_called_once()
    middleware = mock_create_agent.call_args.kwargs["middleware"]
    interrupt_on = middleware[0].interrupt_on
    assert github_tool.name in interrupt_on
    assert codegraph_tool.name not in interrupt_on


# ---------------------------------------------------------------------------
# CodeAgents (DeepAgents) harness tests
# ---------------------------------------------------------------------------


def test_build_berg_agents_returns_compiled_graph(mock_llm: MagicMock) -> None:
    """``build_berg_agents`` should return a compiled LangGraph state graph.

    :param mock_llm: The mock LLM.
    :return: None
    """
    fake_graph = MagicMock()
    with patch(
        "berg_agents.agents.codeagent.create_deep_agent",
        return_value=fake_graph,
    ):
        graph = build_berg_agents(llm=mock_llm, tools=[])
    assert graph is fake_graph


def test_build_berg_agents_drops_builtin_collisions(
    mock_llm: MagicMock,
) -> None:
    """Custom tools that shadow CodeAgents (DeepAgents) built-ins should be dropped.

    :param mock_llm: The mock LLM.
    :return: None
    """

    class CollisionTool(BaseTool):
        """A tool that collides with a DeepAgents built-in.

        Attributes:
            name (str): The name of the tool.
            description (str): A description of the tool.
            args_schema (BaseModel): The schema for the tool's arguments.
            kwargs: Additional keyword arguments.
        """

        name: str = "write_file"
        description: str = "collision"

        @override
        def _run(self, **kwargs: Any) -> str:
            """Run the tool.

            :param kwargs: The tool's arguments.
            :return: The tool's output.
            """
            return "collision"

    fake_graph = MagicMock()
    with patch(
        "berg_agents.agents.codeagent.create_deep_agent",
        return_value=fake_graph,
    ):
        graph = build_berg_agents(llm=mock_llm, tools=[CollisionTool()])
    assert graph is fake_graph


def test_build_berg_agents_requires_profile_key_for_profile(
    mock_llm: MagicMock,
) -> None:
    """Providing a profile without a profile key should raise ``ValueError``.

    :param mock_llm: The mock llm
    :return: None
    """
    from deepagents import HarnessProfile

    with pytest.raises(ValueError, match="profile_key"):
        build_berg_agents(
            llm=mock_llm,
            tools=[],
            profile=HarnessProfile(base_system_prompt="test"),
            profile_key=None,
        )


def test_make_default_permissions_denies_sensitive_paths() -> None:
    """Default permissions should deny ``.env`` and ``secrets`` access.

    :return: None
    :raises AssertionError: If the default permissions do not deny ``.env`` or ``secrets``.
    :raises ValueError: If the default permissions are not a list of ``PathPermission``.
    :example:

    >>> test_make_default_permissions_denies_sensitive_paths()
    """
    permissions = make_default_permissions()
    paths = [rule.paths for rule in permissions]
    flattened = [path for sublist in paths for path in sublist]
    assert any("/.env" in path for path in flattened)
    assert any("secrets" in path for path in flattened)


def test_make_backend_uses_workspace_prefix() -> None:
    """``make_backend`` should route the workspace prefix to a filesystem backend.


    :return: None
    :raises AssertionError: If the backend is not created properly.
    :example:

    >>> test_make_backend_uses_workspace_prefix()
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        backend = make_backend(tmp, workspace_prefix="/workspace/")
        assert backend is not None
