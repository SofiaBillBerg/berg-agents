"""Test suite for the *berg_agents* agent-construction utilities.

The focus is on the agent/LLM helpers:
* :func:`berg_agents.agents.codeagent.build_agent` - creates an agent instance.
* :func:`berg_agents.main.create_llm` - builds an LLM (with graceful fallback).

File-helper coverage (``write_file`` / ``py_to_ipynb``) lives in
``test_file_generator.py`` to avoid duplication.
"""

from pathlib import Path
from typing import Any

import pytest

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

# Import the helpers from the public API
from berg_agents.agents.codeagent import build_agent, create_default_tools
from berg_agents.main import create_llm


# --------------------------------------------------------------------------- #
# Tests for agent creation
# --------------------------------------------------------------------------- #
@pytest.fixture
def dummy_llm() -> BaseChatModel:
    """A dummy LLM for testing agent creation.

    This is a minimal implementation of a BaseChatModel for testing purposes.
    It implements only the required methods to satisfy the ``BaseChatModel``
    interface for testing purposes.
    It always returns a fixed message, making it safe for testing agent
    construction without making actual LLM calls.
    It is used to test agent construction without making real LLM calls.
    See Also:
        ``test_file_generator.py`` for a more complete implementation
        of a dummy LLM for testing file operations.

    :return:
        A dummy LLM instance that returns a fixed message.
    """

    class DummyLLM(BaseChatModel):
        """A  dummy LLM implementation for testing.

        This implementation is minimal and only provides the necessary methods
        to satisfy the ``BaseChatModel`` interface for testing purposes.
        It always returns a fixed message, making it safe for testing agent
        construction without making actual LLM calls.
        It is used to test agent construction without making actual LLM calls.
        """

        def _generate(  # ruff: ignore[no-self-use]
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            **kwargs: Any,
        ) -> ChatResult:  # ty: ignore[invalid-method-override]
            """Generate a fixed message - required by BaseChatModel.

            :param messages: List of messages to generate from.
            :param stop: Stop sequences (not used here).
            :param kwargs: Additional keyword arguments (not used here).
            :return: A fixed ChatResult.
            """
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(content="Hello from DummyLLM")
                    )
                ]
            )

        def bind_tools(
            self, tools: list[BaseTool], **kwargs: Any
        ) -> Runnable[Any, BaseMessage]:  # ty: ignore[invalid-method-override]
            """Bind tools to the LLM - required by BaseChatModel.

            :param tools: List of tools to bind.
            :param kwargs: Additional keyword arguments.
            :return: Self, as no binding occurs in this dummy implementation.
            """
            return self

        @property
        def _llm_type(self) -> str:
            """Acquire the type of the LLM - required by BaseChatModel.

            :return:  The type of the LLM.
            """
            return "dummy-chat-model"

    return DummyLLM()


def test_build_agent_returns_runnable(
    tmp_path: Path, dummy_llm: BaseChatModel
) -> None:
    """Creating an agent with a valid path should return a LangChain Runnable.


    :param tmp_path: Temporary directory path from pytest.
    :param dummy_llm: A dummy LLM instance for testing.
    :raises AssertionError: If the agent is not a Runnable or is None.
    :raises Exception: If the agent creation fails for other reasons.
    """
    # We need to load config and create tools to pass to build_agent
    tools = create_default_tools(root_dir=str(tmp_path), llm=dummy_llm)

    agent_runnable = build_agent(llm=dummy_llm, tools=tools)
    assert isinstance(agent_runnable, Runnable), (
        "build_agent should return a Runnable"
    )
    assert agent_runnable is not None, "Agent Runnable should not be None"


def test_build_agent_with_invalid_config(tmp_path: Path) -> None:
    """Test that agent creation handles invalid configurations gracefully.

    With the current implementation, ``create_llm`` returns a ``ChatOllama``# TODO remove, use langchain directly and init_chat_model
    instance even for invalid configs (construction is lazy). The agent can
    still be built and invoked; any backend errors surface at invocation time.


    :param tmp_path: Temporary directory path from pytest.
    :raises AssertionError: If the agent is not a Runnable.
    :raises Exception: If the agent creation fails unexpectedly.
    """
    # Use a config with an invalid port - ChatOllama construction is lazy # TODO remove, use langchain directly and init_chat_model
    # so this succeeds, but invocation will fail.
    invalid_cfg = {
        "provider": "ollama",
        "model": "nonexistent",
        "ollama_port": 11434,
    }

    llm = create_llm(invalid_cfg)

    # build_agent should still return a Runnable
    tools = create_default_tools(root_dir=str(tmp_path), llm=llm)
    agent_runnable = build_agent(llm=llm, tools=tools)
    assert isinstance(agent_runnable, Runnable), (
        "build_agent should return a Runnable even with invalid LLM config"
    )

    # The agent runnable is created successfully; errors would surface
    # at invocation time when the backend is actually contacted.
