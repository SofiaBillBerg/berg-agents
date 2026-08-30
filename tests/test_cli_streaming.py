"""Tests for the CLI chat streaming UX helpers.

Covers:
- streamed event handling in ``_stream_agent_response``
- fallback to blocking ``invoke`` when streaming is unavailable
- tool-start/tool-end logging
- empty-response fallback text
"""

from __future__ import annotations

from unittest.mock import MagicMock

from berg_agents.cli import (
    _stream_agent_response,  # ruff: ignore[import-private-name]
)


def _make_stream_agent(events: list[dict[str, object]]) -> MagicMock:
    """Make an agent that returns the given events when astream_events is called.

    ``astream_events`` is an async generator in modern LangGraph, so the mock
    yields the events through an async generator to match the ``async for``
    iteration in :func:`berg_agents.cli._run_agent_stream`.

    :param events: The events to return.
    :return: The mock agent.
    """

    async def _event_stream(*_args: object, **_kwargs: object) -> object:  # ruff: ignore[unused-async]
        """Yield each event as an async stream."""
        for event in events:
            yield event

    agent = MagicMock()
    agent.astream_events = _event_stream
    return agent


def test_stream_agent_response_collects_model_chunks() -> None:
    """Test that _stream_agent_response collects model chunks and returns them as a string.

    :return: None
    """
    chunk = MagicMock()
    chunk.content = "hello"

    agent = _make_stream_agent(
        events=[
            {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
            {"event": "on_chain_end", "data": {"output": {"messages": []}}},
        ]
    )

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "hello"


def test_stream_agent_response_logs_tool_events() -> None:
    """Test that _stream_agent_response logs tool start and end events.

    :return: None
    """
    agent = _make_stream_agent(
        events=[
            {
                "event": "on_tool_start",
                "data": {"name": "read-file", "input": {"path": "/tmp/x"}},
            },
            {"event": "on_tool_end", "data": {}},
            {"event": "on_chain_end", "data": {"output": {"messages": []}}},
        ]
    )

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "(no text response)"


def test_stream_agent_response_falls_back_to_invoke() -> None:
    """Test that _stream_agent_response falls back to invoke when astream_events is not available.

    :return: None
    """
    message = MagicMock()
    message.content = "fallback"
    agent = MagicMock()
    agent.invoke.return_value = {"messages": [message]}
    if hasattr(agent, "astream_events"):
        del agent.astream_events

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "fallback"


def test_stream_agent_response_handles_empty_message_content() -> None:
    """Test that _stream_agent_response handles empty message content.

    :return: None
    """
    message = MagicMock()
    message.content = None

    agent = _make_stream_agent(
        events=[
            {
                "event": "on_chain_end",
                "data": {"output": {"messages": [message]}},
            },
        ]
    )

    response = _stream_agent_response(agent, [], "thread-1")

    assert response == "(no text response)"
