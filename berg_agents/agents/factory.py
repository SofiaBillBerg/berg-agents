"""Agent factory for berg_agents.

Framework-free factory that wires the core loop, backend, and file tools.
Uses ``core.tool_spec.make_tool_spec``, ``core.loop.BergLoop``,
``backends.BackendAdapter``, and ``tools._io`` helpers.

Exposes clean names: ``build_agent`` / ``build_loop`` / ``create_tools``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from berg_agents.config.settings import DEFAULT_SYSTEM_PROMPT
from berg_agents.core.checkpoint import Checkpointer
from berg_agents.core.loop import BergLoop
from berg_agents.core.tool_spec import ToolRegistry, ToolSpec, make_tool_spec
from berg_agents.tools._io import _atomic_write, _normalize_target

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "build_agent",
    "build_loop",
    "create_tools"]


def _resolve_root(root_dir: str | Path) -> Path:
    return Path(root_dir).expanduser().resolve()


# -- file tool impls (pure functions, wrapped via make_tool_spec) ----------


def create_tools(root_dir: str | Path = ".") -> list[ToolSpec]:
    """Return the default tool set as ToolSpecs.

    Wraps file ops with *root_dir* captured via closure so the model only
    sees ``file_path`` / ``content`` — not ``root_dir``.

    :param root_dir: Root directory file tools are bound to.
    :return: List of ToolSpec instances.
    """
    root = _resolve_root(root_dir)

    def _read(file_path: str) -> str:
        """Read a file relative to the workspace root.

        :param file_path: Path to the file, may be /workspace-prefixed.
        """
        target = _normalize_target(file_path, root)
        return target.read_text(encoding="utf-8")

    def _edit(file_path: str, content: str) -> str:
        """Edit an existing file (replace contents).

        :param file_path: Path to the file.
        :param content: New file contents.
        """
        target = _normalize_target(file_path, root)
        _atomic_write(target, content)
        return f"Edited {file_path}"

    def _write(file_path: str, content: str) -> str:
        """Create or overwrite a file.

        :param file_path: Path to the file to create.
        :param content: File contents.
        """
        target = _normalize_target(file_path, root)
        _atomic_write(target, content)
        return f"Wrote {file_path}"

    return [
        make_tool_spec(_read, name="read_file", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_edit, name="edit_file", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_write, name="write_file", risk_class="high"),  # type: ignore[arg-type]
    ]


def build_loop(
    adapter: Any,
    tools: Sequence[ToolSpec] | None = None,
    *,
    root_dir: str | Path = ".",
    interrupt_on: Mapping[str, bool] | None = None,
    max_steps: int = 25,
    checkpointer: Checkpointer | None = None,
) -> BergLoop:
    """Build a BergLoop wired for this project.

    :param adapter: Object exposing ``chat(messages, *, tools, temperature)``.
    :param tools: Optional ToolSpecs. Defaults to ``create_tools(root_dir)``.
    :param root_dir: Working directory mounted at /workspace/.
    :param interrupt_on: Optional {tool_name: bool} HITL map.
    :param max_steps: Hard step limit.
    :param checkpointer: Optional checkpointer.
    :return: Configured BergLoop.
    """
    from berg_agents.core.hitl import default_interrupt_on

    registry = ToolRegistry()
    for spec in tools if tools is not None else create_tools(root_dir=root_dir):
        registry.register(spec)

    effective_interrupt: dict[str, bool] = (
        dict(interrupt_on)
        if interrupt_on is not None
        else default_interrupt_on(dict(registry._tools.items()))
    )

    return BergLoop(
        adapter=adapter,
        tool_registry=registry,
        interrupt_on=effective_interrupt,
        max_steps=max_steps,
        checkpointer=checkpointer,
    )


def build_agent(
    adapter: Any,
    tools: Sequence[ToolSpec] | None = None,
    *,
    root_dir: str | Path = ".",
    system_prompt: str | None = None,
    interrupt_on: Mapping[str, bool] | None = None,
    max_steps: int = 25,
    checkpointer: Checkpointer | None = None,
) -> BergLoop:
    """Build an agent loop with a system prompt.

    Thin wrapper over ``build_loop`` that stashes ``system_prompt`` on the
    returned loop for callers to prepend to messages before ``run``.

    :param adapter: LLM adapter (e.g. BackendAdapter).
    :param tools: Optional ToolSpecs.
    :param root_dir: Working directory.
    :param system_prompt: Base system prompt.
    :param interrupt_on: Optional HITL policy.
    :param max_steps: Hard step limit.
    :param checkpointer: Optional checkpointer.
    :return: Configured BergLoop with ``system_prompt`` attribute.
    """
    loop = build_loop(
        adapter=adapter,
        tools=tools,
        root_dir=root_dir,
        interrupt_on=interrupt_on,
        max_steps=max_steps,
        checkpointer=checkpointer,
    )
    loop.system_prompt = (
        system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    )  # type: ignore[attr-defined]
    return loop
