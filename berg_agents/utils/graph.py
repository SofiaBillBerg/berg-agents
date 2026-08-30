"""Agent graph implementation.

Two agent harnesses are supported:

* ``create_agent`` (default) - LangChain's ``create_agent`` with an
  :class:`langgraph.checkpoint.memory.InMemorySaver` checkpointer and a
  :class:`langgraph.middleware.human_in_the_loop.HumanInTheLoopMiddleware` that pauses sensitive tools for approval,
* ``deepagents`` - :func:`berg_agents.agents.codeagent.build_berg_agents`,
  a DeepAgents (LangGraph) agent with the real working directory mounted at
  ``/workspace/``, built-in filesystem tools and permission-based
  human-in-the-loop review.

Both expose the same :class:`~langchain_core.runnables.Runnable` interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from berg_agents.config.mcp import (
    readonly_mcp_tool_names,
    sensitive_mcp_tool_names,
)
from berg_agents.config.settings import DEFAULT_SYSTEM_PROMPT
from langchain.agents import create_agent
from langchain.agents.middleware.human_in_the_loop import (
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
)
from langchain.chat_models import BaseChatModel
from langchain.tools import BaseTool
from langchain_core.runnables import Runnable
from langgraph.checkpoint.memory import InMemorySaver

Harness = Literal["create_agent", "codeagents"]


def build_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    *,
    harness: Harness = "create_agent",
    root_dir: str | Path = ".",
    system_prompt: str | None = None,
    **kwargs: Any,
) -> Runnable:
    """Build an agent graph with the given LLM and tools.

    The harness is selected with *harness*:

    * ``"create_agent"`` (default) - LangChain's ``create_agent`` with an
      :class:`langgraph.checkpoint.memory.InMemorySaver` checkpointer and a
      :class:`langgraph.middleware.human_in_the_loop.HumanInTheLoopMiddleware` that pauses
      write/edit/format/notebook/r-script tools for approval.
    * ``"codeagents"`` - :func:`berg_agents.agents.codeagent.build_berg_agents`
      with the real working directory mounted at ``/workspace/``, built-in
      filesystem tools and permission-based HITL.  Custom tools whose names
      collide with the built-ins are dropped (the built-ins win).

    :param llm: The underlying language model.
    :param tools: A list of tools that the agent can invoke.
    :param harness: Which agent harness to build.
    :param root_dir: Working directory mounted at ``/workspace/`` when
        *harness* is ``"codeagents"``.
    :param system_prompt: Optional system prompt override (codeagents only;
        the ``create_agent`` harness always uses its built-in prompt).
    :param kwargs: Extra keyword arguments forwarded to the harness builder
        (e.g. ``permissions``, ``interrupt_on``, ``profile``).  Only the
        ``codeagents`` harness consumes them.
    :returns: A compiled agent runnable ready for execution.
    """
    if harness == "codeagents":
        from berg_agents.agents.codeagent import build_berg_agents

        return build_berg_agents(
            llm=llm,
            tools=tools,
            root_dir=root_dir,
            system_prompt=system_prompt,
            **kwargs,
        )

    tool_names = {t.name for t in tools}
    interrupt_on: dict[str, bool | InterruptOnConfig] = {}

    if "edit-file" in tool_names:
        interrupt_on["edit-file"] = True
    if "new-file" in tool_names:
        interrupt_on["new-file"] = True
    if "format-code" in tool_names:
        interrupt_on["format-code"] = True
    if "notebook-tool" in tool_names:
        interrupt_on["notebook-tool"] = True
    if "r-script" in tool_names:
        interrupt_on["r-script"] = True

    # External MCP servers that can mutate upstream state (GitHub, memory, ...)
    # are gated server-wide so a prompt-injected instruction surfacing through a
    # tool result cannot silently drive a 'write'. Human-in-the-loop approval is
    # required for every tool those servers expose. A server that is both
    # sensitive and read-only stays autonomous (read-only wins).
    readonly_names = set(readonly_mcp_tool_names(list(tools)))
    for mcp_name in sensitive_mcp_tool_names(list(tools)):
        if mcp_name not in readonly_names:
            interrupt_on[mcp_name] = True

    middleware: list[HumanInTheLoopMiddleware] = []
    if interrupt_on:
        middleware.append(
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="Tool execution requires approval",
            )
        )

    return create_agent(
        model=llm,
        tools=list(tools),
        checkpointer=InMemorySaver(),
        middleware=middleware,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
    )
