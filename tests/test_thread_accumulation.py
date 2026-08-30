"""Regression tests for checkpointer message accumulation.

``build_graph`` wires an :class:`InMemorySaver` checkpointer into
``create_agent``. This means:

* every ``invoke`` must carry ``config={"configurable": {"thread_id": ...}}``;
* state accumulates per ``thread_id`` across turns;
* callers must pass **only the new message(s)** each turn — re-passing the
  full history duplicates messages in the checkpointed state.

These tests pin that behavior so a future refactor cannot silently break it.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from langchain.messages import AIMessage, HumanMessage
from langchain.tools import BaseTool, tool
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver

from berg_agents.utils.graph import build_graph


@pytest.fixture
def mock_llm() -> MagicMock:
    """Return a MagicMock that replies with a plain ``AIMessage``.


    :return: The mock LLM.
    """
    mock = MagicMock()

    def _invoke(messages: list[Any]) -> AIMessage:
        """Return a plain reply.

        :param messages: The messages to process.
        :return: The response message.
        """
        return AIMessage(content="Hello, world!")

    mock.invoke.side_effect = _invoke
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


@pytest.fixture
def dummy_tool() -> BaseTool:
    """A simple dummy tool.

    :return: The dummy tool.
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
    """Build the agent graph wired with the mock LLM and a checkpointer.

    :param mock_llm: The mock LLM.
    :param dummy_tool: The dummy tool.
    :return: The agent graph.
    """
    return build_graph(llm=mock_llm, tools=[dummy_tool])


def _messages_of(state: dict[str, Any]) -> list:
    """Return the message list of a graph state.

    :param state: The graph state.
    :return: The messages list.
    """
    return state.get("messages", [])


def test_checkpointer_accumulates_with_stable_thread_id(
    agent_graph: Any,
) -> None:
    """State should grow across turns when reusing the same ``thread_id``.

    :param agent_graph: The agent graph under test.
    :return: None
    """
    thread_id = str(uuid7())
    config = {"configurable": {"thread_id": thread_id}}

    turn1 = agent_graph.invoke(
        {"messages": [HumanMessage(content="first")]}, config=config
    )
    assert len(_messages_of(turn1)) == 2  # Human + AI

    # Pass ONLY the new message — the checkpointer remembers the rest.
    turn2 = agent_graph.invoke(
        {"messages": [HumanMessage(content="second")]}, config=config
    )
    turn2_msgs = _messages_of(turn2)
    assert len(turn2_msgs) == 4  # first pair + second pair, no duplicates

    contents = [m.content for m in turn2_msgs if isinstance(m, HumanMessage)]
    assert contents == ["first", "second"]


def _replay_from(state: dict[str, Any]) -> list:
    """Rebuild a fresh message list from a graph state.

    Reconstructs ``HumanMessage`` / ``AIMessage`` objects so they carry new
    IDs — this mirrors what real callers do when they rebuild their message
    list from a plain conversation history each turn.

    :param state: The graph state to replay from.
    :return: A fresh list of message objects.
    """
    out: list[Any] = []
    for m in state.get("messages", []):
        if isinstance(m, HumanMessage):
            out.append(HumanMessage(content=m.content))
        elif isinstance(m, AIMessage):
            out.append(AIMessage(content=m.content))
    return out


def test_full_history_repass_duplicates(agent_graph: Any) -> None:
    """Re-passing the full history must NOT be needed — it duplicates state.

    :param agent_graph: The agent graph under test.
    :return: None
    """
    thread_id = str(uuid7())
    config = {"configurable": {"thread_id": thread_id}}

    turn1 = agent_graph.invoke(
        {"messages": [HumanMessage(content="first")]}, config=config
    )

    # Reproduce the naive caller pattern: replay everything seen so far
    # using FRESH message objects (new IDs), like a real caller would.
    replay_msgs = [*_replay_from(turn1), HumanMessage(content="second")]
    turn2 = agent_graph.invoke({"messages": replay_msgs}, config=config)

    turn2_msgs = _messages_of(turn2)
    human_contents = [
        m.content for m in turn2_msgs if isinstance(m, HumanMessage)
    ]
    # "first" appears twice: once from turn 1, once re-passed in turn 2.
    assert human_contents.count("first") == 2


def test_different_thread_ids_are_isolated(agent_graph: Any) -> None:
    """Separate ``thread_id`` values must not share checkpointed state.

    :param agent_graph: The agent graph under test.
    :return: None
    """
    config_a = {"configurable": {"thread_id": str(uuid7())}}
    config_b = {"configurable": {"thread_id": str(uuid7())}}

    agent_graph.invoke(
        {"messages": [HumanMessage(content="for thread A")]}, config=config_a
    )
    turn_b = agent_graph.invoke(
        {"messages": [HumanMessage(content="for thread B")]}, config=config_b
    )

    human_contents = [
        m.content for m in _messages_of(turn_b) if isinstance(m, HumanMessage)
    ]
    assert human_contents == ["for thread B"]  # thread A's message absent
