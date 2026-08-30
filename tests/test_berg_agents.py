"""Minimal test-suite for the *berg_agents* package.

The tests exercise the public API: the file helpers, the CLI, the
scaffold generator and a very small dummy agent.  They run under
``pytest`` and use the ``tmp_path`` fixture to keep the file system
clean.

The test suite is intentionally small but covers the core
behavior.  Feel free to add more tests as you extend the
implementation.
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

import pytest

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.uuid import uuid7
from typer.testing import CliRunner

from berg_agents.agents.codeagent import build_agent
from berg_agents.cli import app as cli_app
from berg_agents.main import load_config


@pytest.fixture
def runner() -> CliRunner:
    """Runner.


    :return: Description of return value.

    Example::

        >>> result = runner()
    """
    return CliRunner()


# ---------------------------------------------------------------------------
# Tests for the CLI
# ---------------------------------------------------------------------------


def test_cli_create(runner: CliRunner, tmp_path: Path) -> None:
    """Test the `create` subcommand.

    :param runner: CliRunner instance from pytest.
    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    file_path = tmp_path / "new.txt"
    result = runner.invoke(
        cli_app, ["create", str(file_path), "--content", "Hello"]
    )
    assert result.exit_code == 0
    assert file_path.read_text() == "Hello"


# ---------------------------------------------------------------------------
# Tests for the agent factory (LLM-independent)
# ---------------------------------------------------------------------------


class DummyLLM(BaseChatModel):
    """A dummy LLM for testing purposes.

    It always returns the same message, regardless of input.

    Attributes:
        _identifying_params: A dictionary of identifying parameters.
        :meta private:
    """

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Access a dictionary of identifying parameters.

        :return: An empty dictionary.
        """
        return {}

    def _generate(
        self,  # r  # ruff: ignore[no-self-use]
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:  # ty: ignore[invalid-method-override]
        """Generate a dummy chat response.

        :param messages: List of messages (ignored).
        :param stop: Stop sequences (ignored).
        :param kwargs: Additional keyword arguments (ignored).
        :return: A dummy ChatResult.
        """
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content="Hello from DummyLLM"))
            ]
        )

    def bind_tools(
        self, tools: list[BaseTool], **kwargs: Any
    ) -> Runnable[Any, BaseMessage]:  # ty: ignore[invalid-method-override]
        """Bind tools to the LLM (dummy implementation).

        :param tools: List of tools to bind.
        :param kwargs: Additional keyword arguments.
        :return: The LLM instance itself.
        """
        return self

    @property
    def _llm_type(self) -> str:
        """Access the type of llm.

        :return: The type of the language model.
        """
        return "dummy-chat-model"


def test_build_agent_returns_runnable(tmp_path: Path) -> None:
    """Verify that build_agent returns a LangChain Runnable.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    dummy_llm_instance = DummyLLM()
    # No tools needed for this basic test
    agent_runnable = build_agent(dummy_llm_instance, [])
    assert isinstance(agent_runnable, Runnable), (
        "build_agent should return a Runnable"
    )
    assert agent_runnable is not None, "Agent Runnable should not be None"

    # Test a basic invocation
    config = {"configurable": {"thread_id": str(uuid7())}}
    result = agent_runnable.invoke(
        {"messages": [HumanMessage(content="test")]},
        config=config,  # ty: ignore[invalid-argument-type]
    )
    final_message = result["messages"][-1]
    assert isinstance(final_message, AIMessage)
    assert final_message.content == "Hello from DummyLLM"


def test_load_config(tmp_path: Path) -> None:
    """Test the ``load_config`` function.

    :param tmp_path: Temporary directory path from pytest.
    :return: None
    """
    cfg_file = tmp_path / "bergagents.jsonc"
    cfg_file.write_text(json.dumps({"model": "gpt-oss:20b"}))
    # Convert Path to string before passing to load_config
    cfg = load_config(str(cfg_file))
    assert cfg["model"] == "gpt-oss:20b"
