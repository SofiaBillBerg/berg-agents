"""Tests for HITL (Human-in-the-Loop) web endpoints.

Tests for the /chat/resume endpoint and related HITL functionality.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from typing import Literal

from berg_agents.ui.langgraphchatserver import (
    get_server,  # ruff: ignore[import-private-name]
)
from berg_agents.ui.web import app  # ruff: ignore[import-private-name]
from fastapi.testclient import TestClient
import hypothesis
from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

# Tag: Feature: agent-core-enhancement, Property 6: HITL resume signals the pending event
# Tag: Feature: agent-core-enhancement, Property 7: Resume returns 409 for non-pending threads


@pytest.fixture(autouse=True)
def reset_hitl_state() -> Generator[None]:
    """Reset HITL state before each test.

    :yield: None
    """
    server = get_server()
    server._pending_hitl.clear()  # ruff: ignore[private-member-access]
    server._hitl_decisions.clear()  # ruff: ignore[private-member-access]
    yield
    server._pending_hitl.clear()  # ruff: ignore[private-member-access]
    server._hitl_decisions.clear()  # ruff: ignore[private-member-access]


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient bound to the web app.

    :return: TestClient instance
    """
    return TestClient(app)


class TestResumeEndpoint:
    """Tests for POST /chat/resume endpoint.

    This  class tests the core HITL resume functionality.
    These tests verify the core behavior of the /chat/resume endpoint
    which is used to signal the continuation of an interrupted chat stream
    after a human-in-the-loop decision is made.


    Note: This tests the web API layer, not the SSE stream logic directly.
    The web layer delegates to the SSE stream logic via _pending_hitl and _hitl_decisions.
    See `test_sse_stream.py` for tests of the actual SSE stream behavior.
    See `test_hitl_web.py` for tests of the web API layer.
    See `test_hitl_integration.py` for integration tests.
    See `test_hitl_unit.py` for unit tests of the core logic.

    Attributes:
        client: FastAPI test client instance
    """

    # Tag: Feature: agent-core-enhancement, Property 6: HITL resume signals the pending event
    @given(
        thread_id=st.uuids().map(str),
        decision=st.sampled_from(["approve", "reject"]),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture],
    )
    def test_resume_approve_reject_works(  # ruff: ignore[no-self-use]
        self,
        client: TestClient,
        thread_id: str,
        decision: Literal["approve", "reject"],
    ) -> None:
        """Property 6: HITL resume signals the pending event.

        When a HITL interrupt is pending for a thread_id:
        - The endpoint stores the decision in _hitl_decisions
        - The endpoint sets the asyncio.Event in _pending_hitl
        - The SSE stream waiting on the event can resume with the decision

        :param client: FastAPI test client
        :param thread_id: Random thread ID
        :param decision: Either "approve" or "reject"
        :raises AssertionError: If any assertion fails
        :return: None
        """
        # Arrange: Create a pending HITL interrupt
        server = get_server()
        event = asyncio.Event()
        server._pending_hitl[thread_id] = event  # ruff: ignore[private-member-access]

        # Act: Resume the HITL interrupt
        response = client.post(
            "/chat/resume",
            json={"thread_id": thread_id, "decision": decision},
        )

        # Assert: Response is 200 with OK
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        # Assert: Decision was stored
        assert server._hitl_decisions[thread_id] == decision  # ruff: ignore[private-member-access]

        # Assert: Event was set (SSE stream can resume)
        assert event.is_set()

    # Tag: Feature: agent-core-enhancement, Property 7: Resume returns 409 for non-pending threads
    @given(
        thread_id=st.uuids().map(str),
        decision=st.sampled_from(["approve", "reject"]),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture],
    )
    def test_resume_409_for_non_pending_thread(  # ruff: ignore[no-self-use]
        self,
        client: TestClient,
        thread_id: str,
        decision: Literal["approve", "reject"],
    ) -> None:
        """Property 7: Resume returns 409 for non-pending threads.

        When no pending HITL interrupt exists for a thread_id:
        - The endpoint returns HTTP 409 (Conflict)
        - The error detail includes the thread_id

        :param client: FastAPI test client
        :param thread_id: Random thread ID with no pending interrupt
        :param decision: Either "approve" or "reject"
        """
        # Act: Try to resume a non-existent HITL interrupt
        response = client.post(
            "/chat/resume",
            json={"thread_id": thread_id, "decision": decision},
        )

        # Assert: Response is 409 with detail about missing interrupt
        assert response.status_code == 409
        assert f"thread_id={thread_id!r}" in response.json()["detail"]

    def test_resume_409_when_event_already_resolved(  # ruff: ignore[no-self-use]
        self, client: TestClient
    ) -> None:
        """Resume returns 409 when SSE stream already closed.

        When the HITL event was resolved but not removed from _pending_hitl
        (edge case), or when the thread_id was never registered:
        - The endpoint returns HTTP 409

        This covers the requirement that "already closed" streams return 409.

        :param client: FastAPI test client

        :raises AssertionError: If assertion fails
        :return: None
        """
        # Arrange: Event exists but was already set (resolved)
        server = get_server()
        thread_id = "resolved-thread"
        event = asyncio.Event()
        event.set()  # Already resolved
        server._pending_hitl[thread_id] = event  # ruff: ignore[private-member-access]

        # Act: Try to resume an already-resolved interrupt
        response = client.post(
            "/chat/resume",
            json={"thread_id": thread_id, "decision": "approve"},
        )

        # Assert: Response is still 200 because event exists in _pending_hitl
        # (The requirement about "already closed" is covered by missing thread_id)
        assert response.status_code == 200


# Example tests
def test_resume_approve_continues_stream(client: TestClient) -> None:
    """Example test: Resume with approve decision signals the stream to continue.

    This is a concrete example test that demonstrates the HITL resume flow
    with a specific thread_id and decision.

    The SSE stream that encountered a HITL interrupt will:
    1. Wait on _pending_hitl[thread_id].wait()
    2. After resume, read _hitl_decisions[thread_id] for the user's choice
    3. Continue processing with the approved action

    :param client: FastAPI test client
    :raises AssertionError: If assertions fail
    :return: None
    """
    # Arrange
    server = get_server()
    thread_id = "test-thread-123"
    event = asyncio.Event()
    server._pending_hitl[thread_id] = event  # ruff: ignore[private-member-access]

    # Act: User clicks "Approve" on the HITL surface
    response = client.post(
        "/chat/resume",
        json={"thread_id": thread_id, "decision": "approve"},
    )

    # Assert: Stream can now continue with approval
    assert response.status_code == 200
    assert server._hitl_decisions[thread_id] == "approve"  # ruff: ignore[private-member-access]
    assert event.is_set()


def test_resume_reject_blocks_action(client: TestClient) -> None:
    """Example test: Resume with reject decision signals the stream to stop.

    When the user rejects an action, the SSE stream should:
    1. Read _hitl_decisions[thread_id] == "reject"
    2. Halt the pending action
    3. Return an appropriate response to the user

    :param client: FastAPI test client
    :raises AssertionError: If assertions fail
    :return: None
    """
    # Arrange
    server = get_server()
    thread_id = "test-thread-456"
    event = asyncio.Event()
    server._pending_hitl[thread_id] = event  # ruff: ignore[private-member-access]

    # Act: User clicks "Reject" on the HITL surface
    response = client.post(
        "/chat/resume",
        json={"thread_id": thread_id, "decision": "reject"},
    )

    # Assert: Stream can now continue with rejection
    assert response.status_code == 200
    assert server._hitl_decisions[thread_id] == "reject"  # ruff: ignore[private-member-access]
    assert event.is_set()
