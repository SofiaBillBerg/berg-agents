"""Unit tests for the public helpers in `berg_agents.tools`."""

from pathlib import Path
from typing import Any

import pytest

from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable

from berg_agents.agents.codeagent import build_agent, create_default_tools
from berg_agents.tools import notebook_tool
from berg_agents.tools._io import (
    create_from_template,  # ruff: ignore[import-private-name]; ruff: ignore[import-private-name]; ruff: ignore[import-private-name]
)


@pytest.fixture
def dummy_llm() -> BaseChatModel:
    """A dummy LLM for testing agent creation.

    :return: A dummy LLM instance of BaseChatModel
    :raises AssertionError: If the dummy LLM setup fails
    :raises ValueError: If the dummy LLM setup fails
    :raises TypeError: If the dummy LLM setup fails
    :raises Exception: If the dummy LLM setup fails for any other reason
    """

    class DummyLLM(BaseChatModel):
        """A dummy LLM implementation for testing."""

        def _generate(  # ruff: ignore[no-self-use]
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            **kwargs: Any,
        ) -> ChatResult:  # ty: ignore[invalid-method-override]
            """Generate a dummy response.

            :param messages: A list of messages
            :param stop: Stop sequences
            :param kwargs: Additional keyword arguments
            :return: A dummy chat result
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
            """Bind tools to the LLM.

            :param tools: A list of tools
            :param kwargs: Additional keyword arguments
            :return: A runnable
            """
            return self

        @property
        def _llm_type(self) -> str:
            """Accessor for the type of chat model this is.

            :return: The type of chat model
            """
            return "dummy-chat-model"

    return DummyLLM()


def test_templates_and_nb(tmp_path: Path, dummy_llm: BaseChatModel) -> None:
    """Test template creation and Python to notebook conversion.

    :param tmp_path: A temporary directory for testing
    :param dummy_llm: A dummy LLM instance
    :return: None
    :raises AssertionError: If template creation or conversion fails
    """
    # Agent creation to ensure context is set up
    tools = create_default_tools(root_dir=str(tmp_path), llm=dummy_llm)
    build_agent(llm=dummy_llm, tools=tools)

    # Test template creation
    template_path = tmp_path / "template.txt"
    template_path.write_text("# {title}\nThis is a template.")

    output_path = tmp_path / "output.md"
    result_path = create_from_template(
        template_path, output_path, replace_vars={"title": "Test Title"}
    )
    assert result_path.exists()

    # Test Python to notebook conversion
    py_path = tmp_path / "test.py"
    py_path.write_text('# %%\nprint("Hello, World!")\n')

    nb_path = tmp_path / "test.ipynb"
    result_path = notebook_tool.py_to_ipynb(py_path, nb_path)
    assert result_path.exists()


@pytest.fixture
def tmp_file(tmp_path: Path) -> Path:
    """A temporary file for testing.

    :param tmp_path: A temporary directory for testing
    :return: A temporary file path
    """
    return tmp_path / "file.txt"
