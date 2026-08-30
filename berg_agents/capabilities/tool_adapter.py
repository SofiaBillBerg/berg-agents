"""Adapt LangChain ``BaseTool`` instances into :class:`Capability` objects.

The :func:`tool_to_capability` factory wraps an existing LangChain tool so it
can be registered in a :class:`CapabilityRegistry` and dispatched through the
standard envelope flow. Tool behavior is preserved: ``invoke`` delegates to
the tool's ``_run`` with the same keyword arguments LangChain would pass.
"""

from __future__ import annotations

from collections.abc import Callable
import inspect
from typing import Any

from .base import CapabilityBase, RiskClass

from berg_agents.config.mcp import (
    is_readonly_server,
    is_sensitive_server,
    server_from_prefixed,
)
from langchain.tools import BaseTool
from pydantic import BaseModel

# Name fragments that suggest a tool only reads, never mutates state.
_READ_ONLY_HINTS: tuple[str, ...] = (
    "read",
    "search",
    "lookup",
    "list",
    "get",
    "explain",
    "inspect",
)


class ToolResult(BaseModel):
    """Uniform output model for an adapted tool invocation.

    Attributes:
        output: The raw value returned by the underlying tool.
    """

    output: Any


def _kebab_case(name: str) -> str:
    """Normalize a tool name into a kebab-case capability id.

    :param name: The tool's ``name`` attribute.
    :return: The name lower-cased with underscores and spaces replaced by hyphens.
    """
    return name.strip().lower().replace("_", "-").replace(" ", "-")


def _infer_risk_class(tool: BaseTool) -> str:
    """Heuristically assign a risk class to a tool.

    Tools originating from a sensitive MCP server (see
    :func:`berg_agents.config.mcp.is_sensitive_server`) are treated as high
    risk; tools from a read-only MCP server (see
    :func:`berg_agents.config.mcp.is_readonly_server`) and tools whose names
    contain read-only hints are treated as low risk; everything else is
    medium risk. This is a simple heuristic - callers may override it with an
    explicit ``risk_class``.

    :param tool: The tool to classify.

    :return: One of the :data:`RiskClass` values.
    """
    server = server_from_prefixed(tool.name)
    if server is not None and is_sensitive_server(server):
        return RiskClass.HIGH
    if server is not None and is_readonly_server(server):
        return RiskClass.LOW
    lowered = tool.name.lower()
    if any(hint in lowered for hint in _READ_ONLY_HINTS):
        return RiskClass.LOW
    return RiskClass.MEDIUM


def _run_requires_config(tool: BaseTool) -> bool:
    """Whether the tool's ``_run`` requires a keyword-only ``config`` argument.

    Recent langchain-core versions made ``config`` a required keyword-only
    argument of ``StructuredTool._run``, so calling ``_run(**kwargs)``
    directly raises a ``TypeError``. Tools with that signature must be
    invoked through the public ``invoke`` API instead, which supplies
    ``config`` internally.

    :param tool: The LangChain tool to inspect.
    :return: ``True`` when ``_run`` declares a ``config`` parameter.
    """
    run = getattr(tool, "_run", None)
    if not callable(run):
        return False
    try:
        return "config" in inspect.signature(run).parameters
    except (TypeError, ValueError):
        # Uninspectable callables (e.g. MagicMock) keep the _run-first path.
        return False


def _make_execute(tool: BaseTool) -> Callable[[BaseModel], BaseModel]:
    """Build the ``_execute`` implementation delegating to a tool.

    The returned callable mirrors ``CapabilityBase._execute``: it receives
    validated parameters and returns an ``output_model`` instance. Tools
    whose ``_run`` requires a ``config`` argument (as in recent
    langchain-core) are invoked through the public ``invoke`` API, which
    supplies ``config`` internally; all other tools keep the original
    ``_run``-first delegation with an ``invoke`` fallback.

    :param tool: The LangChain tool to delegate to.
    :return: A callable from validated params to a :class:`ToolResult`.
    """
    use_invoke = _run_requires_config(tool)

    def execute(params: BaseModel) -> BaseModel:
        """Execute the tool with the given parameters.

        :param params: Validated input parameters.
        :return: A :class:`ToolResult` wrapping the tool's output.
        """
        tool_args = params.model_dump()
        if use_invoke:
            output = tool.invoke(tool_args)
        else:
            try:
                output = tool._run(**tool_args)
            except NotImplementedError:
                output = tool.invoke(tool_args)
        return ToolResult(output=output)

    return execute


def tool_to_capability(
    tool: BaseTool, risk_class: str | None = None
) -> CapabilityBase:
    """Wrap a LangChain ``BaseTool`` into a :class:`CapabilityBase`.

    A dedicated ``CapabilityBase`` subclass is created per tool so the
    derived ``id``, ``intent`` and ``input_model`` are stable class-level
    attributes. The capability id is the tool's kebab-cased name, the intent
    is the tool's description, and the input model is the tool's
    ``args_schema``.

    :param tool: The LangChain tool to adapt.
    :param risk_class: Optional explicit risk class; when omitted it is inferred from the tool name (read-only hints map to low risk).

    :return: A capability wrapping ``tool``, ready for registration in a :class:`CapabilityRegistry`.
    """
    capability_cls = type(
        "ToolCapability",
        (CapabilityBase,),
        {
            "__module__": __name__,
            "id": _kebab_case(tool.name),
            "intent": tool.description or tool.name,
            "input_model": tool.args_schema or BaseModel,
            "output_model": ToolResult,
            "risk_class": risk_class or _infer_risk_class(tool),
            "_execute": staticmethod(_make_execute(tool)),
        },
    )
    return capability_cls()
