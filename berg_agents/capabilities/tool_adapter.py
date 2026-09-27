"""Adapter :class:`ToolSpec` instances into :class:`Capability` objects.

The :func:`tool_to_capability` factory wraps a tool spec so it can be
registered in a :class:`CapabilityRegistry` and dispatched through the
standard envelope flow. Tool behavior is preserved: ``invoke`` delegates to
the spec's ``execute`` callable with the same keyword arguments the spec
declares.

Depends only on Pydantic v2 and the :mod:`berg_agents.core.tool_spec` contract.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import RISK_HIGH, RISK_LOW, CapabilityBase

from berg_agents.config.mcp import (
    is_readonly_server,
    is_sensitive_server,
    server_from_prefixed,
)
from berg_agents.core.tool_spec import ToolSpec, effective_risk_class
from pydantic import BaseModel


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


def _infer_risk_class(tool: ToolSpec) -> str:
    """Heuristically assign a risk class to a tool.

    Tools originating from a sensitive MCP server (see
    :func:`berg_agents.config.mcp.is_sensitive_server`) are treated as high
    risk; tools from a read-only MCP server (see
    :func:`berg_agents.config.mcp.is_readonly_server`) and tools whose names
    contain read-only hints are treated as low risk; everything else is
    medium risk. This is a simple heuristic - callers may override it with an
    explicit ``risk_class``.

    :param tool: The tool spec to classify.

    :return: One of the ``RISK_LOW`` / ``RISK_MEDIUM`` / ``RISK_HIGH`` values.
    """
    server = server_from_prefixed(tool.name)
    if server is not None and is_sensitive_server(server):
        return RISK_HIGH
    if server is not None and is_readonly_server(server):
        return RISK_LOW
    return effective_risk_class(tool)


def _make_execute(tool: ToolSpec) -> Callable[[BaseModel], BaseModel]:
    """Build the ``_execute`` implementation delegating to a tool spec.

    The returned callable mirrors ``CapabilityBase._execute``: it receives
    validated parameters and returns an ``output_model`` instance. The spec's
    ``execute`` callable is invoked with the validated parameters' values.

    :param tool: The  tool spec to delegate to.
    :return: A callable from validated params to a :class:`ToolResult`.
    """

    def execute(params: BaseModel) -> BaseModel:
        """Execute the tool with the given parameters.

        :param params: Validated input parameters.
        :return: A :class:`ToolResult` wrapping the tool's output.
        """
        tool_args = params.model_dump()
        output = tool.execute(**tool_args) if tool.execute is not None else None
        return ToolResult(output=output)

    return execute


def tool_to_capability(
    tool: ToolSpec, risk_class: str | None = None
) -> CapabilityBase:
    """Wrap a  :class:`ToolSpec` into a :class:`CapabilityBase`.

    A dedicated ``CapabilityBase`` subclass is created per tool so the
    derived ``id``, ``intent`` and ``input_model`` are stable class-level
    attributes. The capability id is the tool's kebab-cased name, the intent
    is the tool's description, and the input model is built from the spec's
    parameters via :meth:`ToolSpec.to_pydantic_model`.

    :param tool: The  tool spec to adapt.
    :param risk_class: Optional explicit risk class; when omitted it is
        inferred from the tool name (read-only hints map to low risk).

    :return: A capability wrapping ``tool``, ready for registration in a
        :class:`CapabilityRegistry`.
    """
    input_model = tool.to_pydantic_model(f"{_kebab_case(tool.name)}Input")
    capability_cls = type(
        "ToolCapability",
        (CapabilityBase,),
        {
            "__module__": __name__,
            "id": _kebab_case(tool.name),
            "intent": tool.description or tool.name,
            "input_model": input_model,
            "output_model": ToolResult,
            "risk_class": risk_class or _infer_risk_class(tool),
            "_execute": staticmethod(_make_execute(tool)),
        },
    )
    return capability_cls()
