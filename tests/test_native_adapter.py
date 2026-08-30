"""Tests for berg_agents.backends.native_adapter — framework-free LLM backend."""

import pytest

from berg_agents.backends.native_adapter import NativeAdapter, NativeAgent


# ── NativeAdapter ───────────────────────────────────────────────


class TestNativeAdapter:
    def test_init(self) -> None:
        adapter = NativeAdapter(
            base_url="http://localhost:11434/v1", model="qwen3.5:9b"
        )
        assert adapter.model == "qwen3.5:9b"
        assert adapter.base_url == "http://localhost:11434/v1"

    def test_init_strips_trailing_slash(self) -> None:
        adapter = NativeAdapter(base_url="http://localhost:11434/v1/")
        assert not adapter.base_url.endswith("/")

    def test_from_config(self) -> None:
        adapter = NativeAdapter.from_config({"providers": {}})
        assert isinstance(adapter, NativeAdapter)
        assert isinstance(adapter.model, str)

    def test_chat_raises_on_no_server(self) -> None:
        adapter = NativeAdapter(base_url="http://localhost:19999/v1", timeout=1)
        with pytest.raises(RuntimeError, match="connection|failed|refused"):
            adapter.chat([{"role": "user", "content": "hello"}])


# ── NativeAgent ─────────────────────────────────────────────────


class TestNativeAgent:
    def test_init(self) -> None:
        agent = NativeAgent(name="test")
        assert agent.name == "test"
        assert "native" in agent.capabilities

    def test_can_handle_with_description(self) -> None:
        agent = NativeAgent(name="test")
        assert agent.can_handle({"description": "do something"}) == 0.6

    def test_can_handle_without_description(self) -> None:
        agent = NativeAgent(name="test")
        assert agent.can_handle({"no_description": "x"}) == 0.1

    def test_get_info(self) -> None:
        agent = NativeAgent(name="test")
        info = agent.get_info()
        assert info["name"] == "test"
        assert "native" in info["capabilities"]

    def test_execute_fails_gracefully_no_server(self) -> None:
        adapter = NativeAdapter(base_url="http://localhost:19999/v1", timeout=1)
        agent = NativeAgent(name="test", adapter=adapter)
        from berg_agents.core.interface import TaskContext

        result = agent.execute(
            {"description": "hello"},
            TaskContext(task_id="t1", description="hello"),
        )
        assert result.success is False
        assert result.error is not None
