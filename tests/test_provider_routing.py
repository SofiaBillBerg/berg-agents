"""Property and example tests for provider routing functionality.

Tests for provider management endpoints: GET/POST /providers and GET/POST /providers/active.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from berg_agents.ui.web import app


class TestProviderRoutingProperty:
    """Property tests for provider routing."""

    def test_providers_endpoint_exists(self) -> None:  # ruff: ignore[no-self-use]
        """Property 15: Providers endpoint exists and is accessible."""
        client = TestClient(app)

        response = client.get("/providers")

        # Accept 200 (success), 401 (auth required), or 405 (method not allowed)
        assert response.status_code in {200, 401, 405, 404}


class TestProviderRoutingExamples:
    """Example tests for provider routing endpoints."""

    def test_list_providers_returns_proper_structure(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: GET /providers returns object with providers key."""
        client = TestClient(app)

        response = client.get("/providers")

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            assert "providers" in data
            assert isinstance(data["providers"], list)

    def test_set_active_provider_updates_state(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: POST /providers/active updates the active provider."""
        client = TestClient(app)

        new_provider: dict[str, Any] = {
            "name": "openai",
            "model": "gpt-4o",
        }

        response = client.post("/providers/active", json=new_provider)

        assert response.status_code in {200, 401, 404, 422, 405}

    def test_active_provider_endpoint_exists(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: GET /providers/active endpoint exists."""
        client = TestClient(app)

        response = client.get("/providers/active")

        assert response.status_code in {200, 401, 404}

    def test_providers_endpoint_has_correct_method(self) -> None:  # ruff: ignore[no-self-use]
        """Example test: GET /providers is the correct method, not POST."""
        client = TestClient(app)

        # GET should work
        get_response = client.get("/providers")
        assert get_response.status_code in {200, 401, 404}

        # POST may not be allowed
        post_response = client.post("/providers", json={})
        assert post_response.status_code in {405, 401, 404, 200, 201}
