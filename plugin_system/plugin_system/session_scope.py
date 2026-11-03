# Berg Agents is a sophisticated multi-agent system built with modular, extensible architecture.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Bind plugin tools to per-session storage (the mechanism).

A plugin that keeps state per conversation declares, in its manifest::

    session_scope:
      parameter: todo_path
      subdir: todos

and the plugin system does the rest: every call to those tools is bound
to ``~/.berg-agents/projects/<project-id>/<subdir>/<session-key>/`` and
the declared argument is **removed from the model-visible schema**, so a
model cannot redirect the store.

This module is deliberately plugin-agnostic: nothing here knows what a
todo is. The dependency direction stays one-way — plugins import the
plugin system and berg_agents, never the reverse.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import inspect
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Longest single path segment we will create (session ids get long).
_MAX_SEGMENT = 96


def _safe_segment(value: str, *, fallback: str) -> str:
    """Make one path segment safe to place under the project folder.

    A segment that escapes its parent would move a plugin's store outside
    the project, so anything outside ``[A-Za-z0-9._-]`` becomes ``-`` and
    a name with nothing usable falls back.

    :param value: Raw segment (session id or project id).
    :param fallback: Used when nothing usable survives sanitizing.
    :return: A single safe path segment.
    """
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "._-") else "-" for ch in value
    ).strip(".-")
    return cleaned[:_MAX_SEGMENT] or fallback


def session_dir_for(
    project_dir: Path,
    subdir: str,
    session_id: str | None,
    *,
    default_key: str = "_default",
) -> Path:
    """Resolve one plugin's directory for a project session.

    :param project_dir: The project's folder on disk.
    :param subdir: Manifest-declared folder (e.g. ``todos``).
    :param session_id: Session id, or None for the default key.
    :param default_key: Folder name used when there is no session.
    :return: Absolute path (not created here).
    """
    key = _safe_segment(session_id or "", fallback=default_key)
    return Path(project_dir) / subdir / key


def _rebind_tool(tool: Any, parameter: str, directory: Path) -> Any:
    """Return *tool* with one argument pinned to *directory*.

    :param tool: A ``pydantic_ai.tools.Tool`` (or a bare callable).
    :param parameter: Argument name to bind (e.g. ``todo_path``).
    :param directory: Directory value to supply on every call.
    :return: A new ``Tool`` exposing every argument except *parameter*.
    """
    from pydantic_ai.tools import Tool

    function: Callable[..., Any] = getattr(tool, "function", None) or tool
    signature = inspect.signature(function)
    if parameter not in signature.parameters:
        # The manifest declared a parameter the tool does not take; the
        # tool is still usable, just not session-scoped. Skip binding.
        raise KeyError(
            f"{getattr(tool, 'name', function.__name__)} has no "
            f"parameter {parameter!r}"
        )
    kept = {
        name: param
        for name, param in signature.parameters.items()
        if name != parameter
    }

    def bound(*args: Any, **kwargs: Any) -> Any:
        # The store is decided here; a caller passing the argument is
        # ignored rather than honoured.
        kwargs.pop(parameter, None)
        return function(*args, **{parameter: str(directory)}, **kwargs)

    bound.__name__ = function.__name__
    bound.__qualname__ = function.__qualname__
    bound.__doc__ = function.__doc__
    # Plugin modules annotate with ``Annotated`` for parameter
    # descriptions (often as string annotations under
    # ``from __future__ import annotations``). pydantic-ai resolves type
    # hints against the wrapper's globals, so copy the plugin's across to
    # keep the generated schema identical to the unbound tool's.
    bound.__globals__.update({
        k: v
        for k, v in function.__globals__.items()
        if k not in bound.__globals__
    })
    bound.__annotations__ = {
        k: v for k, v in function.__annotations__.items() if k != parameter
    }
    bound.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=list(kept.values())
    )
    return Tool(bound, name=getattr(tool, "name", function.__name__))


def bind_session_scope(
    tools: Iterable[Any], *, parameter: str, directory: Path
) -> list[Any]:
    """Bind every tool's *parameter* to *directory*.

    Tools that do not take the declared parameter are passed through
    unchanged (they simply are not session-scoped), so one plugin may mix
    scoped and unscoped tools.

    :param tools: Tools to bind.
    :param parameter: Manifest-declared argument name.
    :param directory: Directory the bound tools must use.
    :return: New tool list; unbound tools keep their original identity.
    """
    directory.mkdir(parents=True, exist_ok=True)
    out: list[Any] = []
    for tool in tools:
        try:
            out.append(_rebind_tool(tool, parameter, directory))
        except KeyError:
            out.append(tool)
        except Exception as exc:  # Defensive: never fail a whole turn.
            logger.warning(
                "Could not bind %s to %s: %s",
                getattr(tool, "name", tool),
                directory,
                exc,
            )
            out.append(tool)
    return out
