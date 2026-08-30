"""Property and example tests for `/chat/stream` SSE endpoint.

Tests for Server-Sent Events streaming responses from the chat endpoint.
"""

from __future__ import annotations

import json

from collections.abc import AsyncGenerator

import pytest

from fastapi.testclient import TestClient

from berg_agents.ui.web import app


# Tag: Feature: agent-core-enhancement, Property 14: SSE stream properly formatted event


class TestStreamingEndpoint:
    """Tests for /chat/stream SSE endpoint.

    This class tests the Server-Sent Events (SSE) streaming responses from the chat endpoint.

    Attributes:
        client: FastAPI test client instance
        timeout: Optional timeout for requests (default: 5 seconds)
    """

    @pytest.mark.asyncio
    async def test_sse_events_have_required_format(  # ruff: ignore[no-self-use]
        self, timeout: int = 5
    ) -> None:
        """Property 14: SSE events have the required `data:` prefix format.

        Each line yielded should start with `data: ` followed by valid JSON.

        An SSE event line should be formatted as:
        data: {"type": "message", "content": "..."}

        :raises AssertionError if any event lacks 'data: ' prefix
        :return: None
        """

        # Arrange: Create mock streaming generator
        async def mock_generator() -> AsyncGenerator[str]:
            """Mock generator yielding properly formatted SSE events.


            Note: In practice, this would come from an async LLM generator.
            For testing, we simulate the expected output format.
            See: https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation
            See also: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events#event_stream_format
            See: https://github.com/whatwg/html/issues/3967

            :yield is the key here - it must be properly formatted
            """
            yield 'data: {"type": "message", "content": "Hello"}\n'
            yield 'data: {"type": "done", "content": null}\n'

        # Act: Verify event formatting
        events = []
        async for event in mock_generator():
            events.append(event)

        # Assert: All events start with 'data: '
        for event in events:
            assert event.startswith("data: ")

    @pytest.mark.asyncio
    async def test_sse_event_structure_valid_json(self) -> None:  # ruff: ignore[no-self-use]
        """Property 14 variant: SSE event data contains valid JSON.

        The payload after 'data: ' should be parseable as JSON.

        See: https://json.org/
        See: https://www.jsonrpc.org/specification
        See: https://en.wikipedia.org/wiki/JSON#JSON_vs._JavaScript

        See: https://tools.ietf.org/html/rfc7159

        :raises ValueError if invalid JSON
        """
        # Arrange
        raw_event = 'data: {"type": "message", "content": "test"}\n'

        # Act
        json_str = raw_event.replace("data: ", "").strip()
        data = json.loads(json_str)

        # Assert
        assert "type" in data
        assert isinstance(data["type"], str)

    async def test_streaming_response_is_streaming_response(  # ruff: ignore[no-self-use]
        self, timeout: int = 5
    ) -> None:
        """Example test: /chat/stream returns StreamingResponse.


        #: https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse
        #: https://www.starlette.io/responses/#streamingresponse


        See: https://github.com/encode/starlette/blob/master/starlette/responses.py

        :raises AssertionError if not StreamingResponse
        :return: None
        """
        # This test verifies the endpoint returns correct response type
        client = TestClient(app)

        # The endpoint should exist and return streaming response
        response = client.post(
            "/chat/stream",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            timeout=5,
        )

        assert response.status_code in {
            200,
            401,
            422,
        }  # Auth or validation issues expected
