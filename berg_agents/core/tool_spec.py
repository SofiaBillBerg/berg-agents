"""Native tool specification and registry.

This module defines the :class:`ToolSpec` and :class:`ToolRegistry` classes, which are the core of BergAgents' tool system.
The spec is framework-free and can be used with any provider that supports tool calling,
while the registry allows for easy management and filtering of tools.
:mod:`berg_agents.tools`.  The goal of this module is to give BergAgents a
typed tool contract that any provider can consume (OpenAI function calling,
Anthropic tool use, MCP wire) and that any agent can filte

The key idea: a tool is just a *spec* (name, description, JSON-Schema
parameters, an executable) plus a *registry* that lets the agent select
tools by tag, by glob, or by per-model exclusion patterns.  The spec is
deliberately small and serialisable so it can ride the wire as a tool-use
schema or be persisted to MemPalace.
"""

from __future__ import annotations

import fnmatch
import inspect

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, get_args, get_origin

from pydantic import BaseModel, Field, create_model

from berg_agents.capabilities.base import (
    RiskClass,  # canonical risk vocabulary
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Name fragments that suggest a tool only reads, never mutates state.
#: Mirrors ``_READ_ONLY_HINTS`` in :mod:`berg_agents.capabilities.tool_adapter`
#: so a native spec infers the same risk class as the MCP adapter.
_READ_ONLY_HINTS: tuple[str, ...] = (
    "read",
    "search",
    "lookup",
    "list",
    "get",
    "explain",
    "inspect",
)


# ---------------------------------------------------------------------------
# Pydantic parameter model (describes a single JSON-Schema property)
# ---------------------------------------------------------------------------


class ToolParam(BaseModel):
    """One JSON-Schema property for a tool's input.

    Mirrors OpenAI function-calling shape (and is close enough to Anthropic
    tool-use that ``to_anthropic_tool`` is a trivial rename).  Default
    comes from the spec; type and required are derived from the executable
    signature when ``make_tool_spec`` is used.

    :param name: Parameter name (snake_case by convention).
    :param type: JSON-Schema-style type (``string`` / ``integer`` / ``number``
        / ``boolean`` / ``array`` / ``object`` / ``null``).
    :param description: Human-readable description surfaced to the model.
    :param required: Whether the parameter must be supplied.
    :param enum: Optional list of allowed values (enum constraint).
    :param default: Optional default; ``None`` means *no default*.
    """

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: list[Any] | None = None
    default: Any = None


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Framework-free description of a single tool.

    A ``ToolSpec`` is what the model *sees* (``name`` / ``description`` /
    ``params``) and what the runtime *executes* (``execute``).  Both halves
    are framework-agnostic: the same spec can be wired into an OpenAI
    function-calling call, an Anthropic tool-use block, or a local CLI.

    :param name: Stable tool id (kebab-case or snake_case; treated as
        the public name everywhere).
    :param description: One-sentence summary shown to the model.
    :param params: Ordered list of parameters (preserved in the wire
        schema).
    :param execute: Callable implementing the tool.  Receives keyword
        arguments matching ``params`` and returns any value the
        provider can serialise.
    :param tags: Optional labels for grouping (``"fs"``, ``"read"``,
        ``"mcp"``, ...).
    :param risk_class: Optional explicit risk class.  When ``None`` the
        registry will infer it from ``name`` via :func:`infer_risk_class`.
    """

    name: str
    description: str
    params: tuple[ToolParam, ...] = ()
    execute: Callable[..., Any] | None = None
    tags: tuple[str, ...] = ()
    risk_class: RiskClass | None = None

    # -- Serialisation -----------------------------------------------------

    def to_openai_tool(self) -> dict[str, Any]:
        """Render the spec as an OpenAI ``tools[]`` entry.

        :return: ``{"type": "function", "function": {...}}``.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._json_schema()}}

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Render the spec as an Anthropic ``tools[]`` entry.

        Anthropic tool use uses the same JSON-Schema shape with one extra
        ``input_schema`` wrapper; ``parameters`` is renamed accordingly.

        :return: ``{"name": ..., "description": ..., "input_schema": {...}}``.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._json_schema()}

    def _json_schema(self) -> dict[str, Any]:
        """Render the params as a JSON-Schema ``object``.

        :return: ``{"type": "object", "properties": {...}, "required": [...]}``.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.params:
            prop: dict[str, Any] = {"type": p.type}
            if p.description:
                prop["description"] = p.description
            if p.enum is not None:
                prop["enum"] = p.enum
            if not p.required and p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    # -- Helpers -----------------------------------------------------------

    def to_pydantic_model(self, model_name: str) -> type[BaseModel]:
        """Build a Pydantic v2 model that matches the spec.

        Useful for the native loop, which validates tool calls through
        Pydantic before invoking :attr:`execute`.

        :param model_name: Class name for the generated model.
        :return: A ``pydantic.BaseModel`` subclass.
        """
        fields: dict[str, Any] = {}
        for p in self.params:
            annotation = _json_type_to_python(p.type)
            if p.required:
                fields[p.name] = (annotation, Field(description=p.description))
            else:
                default = p.default if p.default is not None else None
                fields[p.name] = (
                    annotation,
                    Field(default=default, description=p.description),
                )
        return create_model(model_name, **fields)  # type: ignore[call-overload]

    @property
    def is_read_only(self) -> bool:
        """Whether this tool's name matches one of the read-only hints.

        :return: ``True`` when the name contains a read-only hint.
        """
        lowered = self.name.lower()
        return any(hint in lowered for hint in _READ_ONLY_HINTS)


# ---------------------------------------------------------------------------
# Risk-class inference
# ---------------------------------------------------------------------------


def infer_risk_class(name: str) -> RiskClass:
    """Infer a tool's risk class from its name.

    Tools whose names contain read-only hints map to ``"low"``; everything
    else defaults to ``"medium"``.  :func:`tool_adapter._infer_risk_class`
    builds on this by adding MCP-server-based classification (sensitive
    servers map to ``"high"``, read-only servers to ``"low"``).

    :param name: Tool name.
    :return: ``"low"`` / ``"medium"`` / ``"high"``.
    """
    lowered = name.lower()
    if any(hint in lowered for hint in _READ_ONLY_HINTS):
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Pydantic-from-function helper
# ---------------------------------------------------------------------------


def _json_type_to_python(json_type: str) -> Any:
    """Map a JSON-Schema-style type to a Python annotation.

    :param json_type: JSON-Schema type (``"string"``/``"integer"``/...).
    :return: Python annotation (used to build Pydantic models).
    """
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None)}.get(json_type, str)


def _python_type_to_json(annotation: Any) -> str:
    """Map a Python annotation to a JSON-Schema-style type.

    Strips ``Optional[...]`` / ``Union[..., None]`` and chooses the first
    non-``None`` member.  Defaults to ``"string"`` when nothing matches.

    :param annotation: Python type or ``typing`` form.
    :return: JSON-Schema type string.
    """
    if annotation is None or annotation is type(None):
        return "null"
    origin = get_origin(annotation)
    if origin is not None:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            return _python_type_to_json(args[0])
    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is list:
        return "array"
    if annotation is dict:
        return "object"
    return "string"


def _resolve_annotation(
    annotation: Any,
    *,
    func: Callable[..., Any] | None = None,
    name: str | None = None,
) -> Any:
    """Resolve a string annotation to its real type when possible.

    Modules that use ``from __future__ import annotations`` expose
    annotations as strings at runtime.  This helper consults
    :func:`typing.get_type_hints` to turn them back into real types so
    type-inference downstream (``_python_type_to_json``) sees ``int`` and
    not ``"int"``.

    :param annotation: Raw annotation (possibly a string).
    :param func: The owning function (used as the resolution context).
    :param name: Parameter name (used to index the resolved hints).
    :return: The resolved annotation, or the input as-is when resolution
        is not possible.
    """
    if not isinstance(annotation, str):
        return annotation
    if func is None or name is None:
        return annotation
    import typing as _typing

    try:
        hints = _typing.get_type_hints(func, include_extras=False)
    except Exception:
        return annotation
    return hints.get(name, annotation)


def _param_from_signature(
    name: str,
    annotation: Any,
    default: Any,
    docstring_param_desc: str,
    *,
    func: Callable[..., Any] | None = None,
) -> ToolParam:
    """Build a :class:`ToolParam` from a function-signature entry.

    :param name: Parameter name.
    :param annotation: Python annotation (may be a string when
        ``from __future__ import annotations`` is in effect).
    :param default: Default value or :data:`inspect.Parameter.empty`.
    :param docstring_param_desc: Description pulled from the function's
        docstring (Google / reST style ``:param name:`` lines).
    :param func: The owning function (used to resolve string annotations).
    :return: The constructed :class:`ToolParam`.
    """
    required = default is inspect.Parameter.empty
    resolved = _resolve_annotation(annotation, func=func, name=name)
    json_type = _python_type_to_json(resolved)
    return ToolParam(
        name=name,
        type=json_type,
        description=docstring_param_desc,
        required=required,
        default=None if required else default,
    )


def _parse_param_descriptions(docstring: str | None) -> dict[str, str]:
    """Extract ``:param name: description`` lines from a docstring.

    Accepts reST-style (``":param x: ..."``) and Google-style
    (``"Args: x -- ..."`` -- basic form, ``--`` separator) and returns
    ``{param_name: description}`` for the union of the two.

    :param docstring: The function's docstring.
    :return: Mapping of parameter name to its description.
    """
    descriptions: dict[str, str] = {}
    if not docstring:
        return descriptions

    for line in docstring.splitlines():
        stripped = line.strip()
        # reST-style: ":param name: description"
        if stripped.startswith(":param"):
            rest = stripped[len(":param") :].strip()
            if ":" in rest:
                pname, pdesc = rest.split(":", 1)
                descriptions[pname.strip()] = pdesc.strip()
                continue
        # Google-style: "name -- description" or "name: description"
        for sep in (" -- ", ":"):
            if sep in stripped and not stripped.startswith(":"):
                # Skip headings like "Args:" / "Returns:" by requiring a
                # lowercase param-name candidate.
                pname, _, pdesc = stripped.partition(sep)
                pname = pname.strip()
                if pname and pname[0].islower():
                    descriptions.setdefault(pname, pdesc.strip())
    return descriptions


def make_tool_spec(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    tags: Iterable[str] = (),
    risk_class: RiskClass | None = None,
) -> ToolSpec:
    """Build a :class:`ToolSpec` from a plain function.

    The function's signature becomes the spec's parameters, with defaults
    and types inferred; the function's docstring is parsed for
    ``:param name:`` lines and used to populate per-parameter
    descriptions.

    :param func: The function implementing the tool.
    :param name: Override name; defaults to ``func.__name__``.
    :param description: Override description; defaults to the function's
        docstring's first line.
    :param tags: Optional tag list.
    :param risk_class: Optional explicit risk class.
    :return: The constructed :class:`ToolSpec`.
    :raises TypeError: If *func* is not a callable.
    """
    if not callable(func):
        raise TypeError("make_tool_spec requires a callable")

    sig = inspect.signature(func)
    desc_map = _parse_param_descriptions(func.__doc__)
    params: list[ToolParam] = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        params.append(
            _param_from_signature(
                pname,
                param.annotation,
                param.default,
                desc_map.get(pname, ""),
                func=func,
            )
        )

    doc = (func.__doc__ or "").strip()
    first_line = doc.split("\n", 1)[0].strip() if doc else ""
    return ToolSpec(
        name=getattr(name or func.__name__, "strip", lambda: func.__name__)(),
        description=description or first_line,
        params=tuple(params),
        execute=func,
        tags=tuple(tags),
        risk_class=risk_class,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class ToolRegistry:
    """In-process tool registry with lookup and filter helpers.

    The registry is intentionally tiny: register, unregister, get, all,
    plus a few filter helpers (``by_tag``, ``by_name_glob``,
    ``by_risk_class``) and a generic ``filter(predicate)``.  It has no
    persistence, no LLM access, and no framework dependencies.

    :ivar _tools: Map of tool name -> :class:`ToolSpec`.
    """

    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, tool: ToolSpec) -> None:
        """Register *tool*, replacing any existing entry with the same name.

        :param tool: The :class:`ToolSpec` to register.
        """
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove the tool with the given name, if any.

        :param name: Tool name.
        """
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        """Return the tool with *name* or ``None``.

        :param name: Tool name.
        :return: The :class:`ToolSpec` or ``None``.
        """
        return self._tools.get(name)

    def all(self) -> list[ToolSpec]:
        """Return all registered tools, sorted by name.

        :return: Sorted list of :class:`ToolSpec`.
        """
        return [self._tools[name] for name in sorted(self._tools)]

    def names(self) -> list[str]:
        """Return all registered tool names, sorted.

        :return: Sorted list of names.
        """
        return sorted(self._tools)

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        """Return ``True`` if *name* is a registered tool.

        :param name: Tool name to check.
        """
        return name in self._tools

    # -- Filters -----------------------------------------------------------

    def by_tag(self, tag: str) -> list[ToolSpec]:
        """Return all tools tagged with *tag*.

        :param tag: Tag to match.
        :return: Matching tools.
        """
        return [t for t in self.all() if tag in t.tags]

    def by_name_glob(self, pattern: str) -> list[ToolSpec]:
        """Return all tools whose name matches *pattern* (``fnmatch``).

        :param pattern: Glob pattern, e.g. ``"mcp_*"``.
        :return: Matching tools.
        """
        return [t for t in self.all() if fnmatch.fnmatchcase(t.name, pattern)]

    def by_risk_class(self, risk: RiskClass) -> list[ToolSpec]:
        """Return all tools whose effective risk class equals *risk*.

        The effective risk class is ``spec.risk_class`` when set,
        otherwise :func:`infer_risk_class` from the name.

        :param risk: ``"low"``/``"medium"``/``"high"``.
        :return: Matching tools.
        """
        return [t for t in self.all() if effective_risk_class(t) == risk]

    def filter_by_model(self, model_id: str) -> list[ToolSpec]:
        """Filter tools by the model's ``excluded_tools`` patterns.

        Delegates to :func:`berg_agents.profiles.router.filter_tools_by_exclusions`
        so per-model exclusion logic stays in one place. Tools matching
        an exclusion pattern (exact name or glob) are removed.

        :param model_id: Model identifier as declared in providers.
        :return: Filtered list of specs (order preserved).
        """
        return filter_specs_by_model(self.all(), model_id)

    def filter(self, predicate: Callable[[ToolSpec], bool]) -> list[ToolSpec]:
        """Return tools for which *predicate* is true.

        :param predicate: Callable from spec to bool.
        :return: Matching tools.
        """
        return [t for t in self.all() if predicate(t)]


# ---------------------------------------------------------------------------
# Effective risk class
# ---------------------------------------------------------------------------


def effective_risk_class(tool: ToolSpec) -> RiskClass:
    """Return the effective risk class for *tool*.

    Uses ``tool.risk_class`` when set, otherwise infers it from the
    tool's name.

    :param tool: The :class:`ToolSpec`.
    :return: ``"low"``/``"medium"``/``"high"``.
    """
    if tool.risk_class is not None:
        return tool.risk_class
    return infer_risk_class(tool.name)


# ---------------------------------------------------------------------------
# Per-model filtering (interop with profiles/router.py)
# ---------------------------------------------------------------------------


def filter_specs_by_model(
    tools: Iterable[ToolSpec],
    model_id: str,
) -> list[ToolSpec]:
    """Filter specs by the model's ``excluded_tools`` patterns.

    Delegates to :func:`berg_agents.profiles.router.filter_tools_by_exclusions`
    so the per-provider/per-model exclusion logic stays in one place.  The
    helper is interop: it only needs the tool's ``.name``, which
    :class:`ToolSpec` exposes directly.

    :param tools: Specs to filter.
    :param model_id: Model identifier.
    :return: Filtered list of specs (order preserved).
    """
    try:
        from berg_agents.profiles.router import filter_tools_by_exclusions
    except ImportError:
        return list(tools)
    return list(filter_tools_by_exclusions(list(tools), model_id))
