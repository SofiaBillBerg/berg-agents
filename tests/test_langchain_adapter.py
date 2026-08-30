"""Tests for berg_agents.backends.langchain_adapter — LangChain bridge."""

import pytest

from berg_agents.backends.langchain_adapter import (
    LangChainAdapter,
    LangGraphAgent,
    is_langchain_available,
)


# ── is_langchain_available ──────────────────────────────────────


class TestLangChainAvailability:
    def test_returns_bool(self) -> None:
        result = is_langchain_available()
        assert isinstance(result, bool)


# ── LangChainAdapter ────────────────────────────────────────────


class TestLangChainAdapter:
    def test_init_raises_if_no_langchain(self) -> None:
        """Adapter raises ImportError if LangChain not installed."""
        if not is_langchain_available():
            with pytest.raises(ImportError, match="LangChain"):
                LangChainAdapter(llm=None)

    def test_init_succeeds_if_langchain_available(self) -> None:
        """Adapter initializes when LangChain is available."""
        if is_langchain_available():
            adapter = LangChainAdapter(llm=None)
            assert adapter.llm is None
            assert adapter.checkpointer is None

    def test_create_native_agent(self) -> None:
        """create_native_agent returns a LangGraphAgent."""
        if is_langchain_available():
            adapter = LangChainAdapter(llm=None)
            agent = adapter.create_native_agent("test_agent")
            assert isinstance(agent, LangGraphAgent)
            assert agent.name == "test_agent"


# ── LangGraphAgent ──────────────────────────────────────────────


class TestLangGraphAgent:
    def test_init(self) -> None:
        agent = LangGraphAgent(name="test")
        assert agent.name == "test"
        assert "langgraph" in agent.capabilities
        assert agent.preferred_model_tier == "medium"

    def test_can_handle_with_description(self) -> None:
        agent = LangGraphAgent(name="test")
        confidence = agent.can_handle({"description": "do something"})
        assert confidence == 0.7

    def test_can_handle_without_description(self) -> None:
        agent = LangGraphAgent(name="test")
        confidence = agent.can_handle({"no_description": "x"})
        assert confidence == 0.1

    def test_get_info(self) -> None:
        agent = LangGraphAgent(name="test")
        info = agent.get_info()
        assert info["name"] == "test"
        assert "langgraph" in info["capabilities"]

    def test_description_attribute(self) -> None:
        agent = LangGraphAgent(name="my_agent")
        assert "my_agent" in agent.description
