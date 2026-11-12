#  Copyright (c) 2026 Sofia Billger Bergström
#

# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
#
# This program is free software: you can redistribute it and/or modify
#
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

"""Workspace toolset for berg_agents chat agents.

Wraps the framework-free :class:`~berg_agents.tools.tool_spec.ToolSpec`
instances from :func:`~berg_agents.agents.factory.create_tools` in a
single named pydantic-ai toolset, following the documented custom-toolset
pattern (subclass :class:`~pydantic_ai.toolsets.WrapperToolset`,
override the extension points you need, delegate the rest).

Why a toolset instead of loose ``tool_plain`` registrations:

- One stable ``id`` (``"workspace"``) identifying every instruction
  and tool the workspace contributes - addressable as
  ``toolset:workspace`` and safe for durable execution.
- One ``get_instructions`` block teaching explore-first usage, instead
  of repeating usage guidance per tool and in the system prompt.
- Dynamic membership: ``read_only`` / ``allow_shell`` constructor
  flags select the registered subset per deployment, and ``call_tool``
  is the single audit/logging switch for every invocation.
- The harness loop and ``POST /api/tool/execute`` keep using the raw
  :class:`ToolSpec` list - this toolset is the pydantic-ai view of
  the same single source, not a second one.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, override

from pydantic_ai.toolsets.wrapper import WrapperToolset

from berg_agents.tools._io import _atomic_write, _normalize_target
from berg_agents.tools.tool_spec import RiskClass, ToolSpec, make_tool_spec

logger = logging.getLogger(__name__)

#: Stable toolset id. Instruction parts from
#: :meth:`WorkspaceToolset.get_instructions` are addressable as
#: ``toolset:workspace``; keep it constant - durable execution and
#: log readers key off this string, never the wording.
WORKSPACE_TOOLSET_ID = "workspace"

#: Usage guide injected into the agent's instructions once per run.
#: Complements (not replaces) the system prompt's authoritative tool
#: list: this text teaches *how* to work the filesystem, the prompt
#: names *what* exists.
_WORKSPACE_INSTRUCTIONS = """\
Workspace tools (toolset `workspace`) - how to work the filesystem:

- EXPLORE FIRST: call list_files before reading anything. Never guess
  at paths; use the exact paths list_files returns.
- Directories are not files: read_file on a directory tells you so -
  follow its guidance instead of retrying.
- SEARCH before assuming: use search_code to find definitions,
  references, or error strings instead of reading trees by hand.
- RUN things with bash (tests, builds, inspection). It has a timeout
  and truncated output; long jobs should be split or backgrounded by
  the caller. There is no other shell tool.
- WRITE with intent: write_file creates, edit_file replaces. Both
  need human approval in chat - the user sees an approve/reject
  dialog, so say what you are about to do before calling.
- COMPLEX work (multistep plans, refactors, research) starts with
  plan_task, which writes the plan into this session's todo list (the
  plan panel the user can see and edit). Then delegate the plan: read
  it back with list_subtasks, and pass its steps to the implementation
  delegate with delegate_task. Its work streams inside its own card, so
  progress stays visible.
- The todo list IS the plan. If the user edits it, that edited version
  is what you hand to the delegate — never re-plan over their changes.
  Use the todo tools to update it (add_subtask, complete_todo) instead
  of restating the plan in chat.
- If a tool answers "not found" or "is a directory", follow the
  message. Do not retry the same call and do not invent tool names —
  the toolset above is the complete inventory.
"""


class WorkspaceToolset(WrapperToolset[None]):
    """File/shell workspace tools as one named, dynamic toolset.

    Builds an inner :class:`FunctionToolset` from
    :func:`~berg_agents.agents.factory.create_tools` (the same specs
    the harness loop and ``/api/tool/execute`` run) plus the staged
    ``plan_task`` delegate, then adds identity, instructions, dynamic
    membership, and an audited call path on top.

    :param root_dir: Workspace root all file tools are bound to.
    :param read_only: When True, only low-risk tools (list, read,
        search) are registered - the model cannot change files even
        if it tries. Mutating tools are withheld, not merely
        instructed away.
    :param allow_shell: When False, the ``bash`` tool is withheld
        (safe default for untrusted deployments).
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        read_only: bool = False,
        allow_shell: bool = True,
        plan_tools: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the workspace toolset.

        :param root_dir: Workspace root all file tools are bound to.
        :param read_only: When True, only low-risk tools (list, read,
            search) are registered - the model cannot change files even
            if it tries. Mutating tools are withheld, not merely
            instructed away.
        :param allow_shell: When False, the ``bash`` tool is withheld
            (safe default for untrusted deployments).
        :param plan_tools: The session-bound plan-store tools, keyed by
            the names the delegates call (``create_todo``,
            ``add_subtask``, ``list_subtasks``).
            Both delegates go through these, so the plan they write and
            the plan they execute is the one store the user also edits —
            never a string passed between stages. When None the staged
            delegates are withheld entirely: a planner with nowhere to
            write a plan would otherwise hand back prose that the
            implementer has to guess at, which is the seam this replaced.
        """
        from pydantic_ai.toolsets import FunctionToolset

        inner: FunctionToolset[None] = FunctionToolset()
        # The planner subagent's read-only tool set: it may ground a plan
        # in the repo it plans for, but the plan itself is written by the
        # plan_task delegate alone. Store write tools are withheld here
        # on purpose — a planner with store tools created its own todo,
        # and the delegate then created a second from its text output.
        read_tools: list[Any] = []
        for spec in create_tools(root_dir):
            if spec.execute is None:
                logger.warning(
                    "ToolSpec '%s' has no execute callable; skipping", spec.name
                )
                continue
            risk = spec.risk_class or "medium"
            if read_only and risk != "low":
                continue
            if not allow_shell and spec.name == "bash":
                continue
            if risk == "low":
                read_tools.append(spec.execute)
            inner.add_function(
                spec.execute,
                name=spec.name,
                description=spec.description or spec.name,
                requires_approval=risk != "low",
            )
        missing = _missing_plan_tools(plan_tools)
        if not read_only and not missing and plan_tools is not None:
            # Staged delegation over ONE plan store: plan_task writes the
            # plan into the session's todo list, and the delegate reads it
            # back by id. The user sees and edits that same list, so the
            # views never diverge.
            inner.add_function(
                _make_plan_task(plan_tools, read_tools),
                name="plan_task",
                description=(
                    "Decompose a task into an ordered step plan and write "
                    "it to this session's todo list. Returns the plan's "
                    "id, which the implementation delegate consumes."
                ),
                requires_approval=False,
                timeout=240.0,
            )
        elif not read_only:
            # Say so rather than registering a planner that cannot store
            # what it plans.
            logger.warning(
                "Workspace stage tools withheld: plan store tools missing "
                "(%s). The todo plugin must grant the planner and "
                "implementer roles.",
                ", ".join(missing),
            )
        super().__init__(wrapped=inner)
        self._root_dir = str(root_dir)

    @property
    def id(self) -> str | None:
        """Stable toolset id (``"workspace"``).

        :return: Toolset id.
        """
        return WORKSPACE_TOOLSET_ID

    # Overrides the framework toolset extension point
    # (WrapperToolset/AbstractToolset.get_instructions), so it stays an
    # instance method even though it ignores ``self``; ``@override``
    # declares that contract instead of a static-method rewrite.
    @override
    async def get_instructions(self, ctx: Any) -> str:
        """Workspace usage guide, injected once per run.

        :param ctx: Context from the agent.
        :return: Usage instructions for the workspace toolset.
        """
        _ = ctx
        return _WORKSPACE_INSTRUCTIONS

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any
    ) -> Any:
        """Audit-log every invocation, then delegate to the toolset.

        The single switch for all workspace tool execution: approval
        gating, retries, and result handling stay in the framework
        (via each tool's registration metadata); this layer owns
        observability.
        """
        logger.info("workspace tool call: %s(%s)", name, tool_args)
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            logger.warning("workspace tool %s failed: %s", name, exc)
            raise
        logger.debug(
            "workspace tool %s returned %d chars", name, len(str(result))
        )
        return result


#: Plan-store tools the staged delegates need, by name. Both delegates go
#: through the same store, so this is the minimum a working plan pipeline
#: requires; the todo plugin grants all four to the planner and implementer.
_REQUIRED_PLAN_TOOLS = ("create_todo", "add_subtask", "list_subtasks")


def _missing_plan_tools(plan_tools: dict[str, Any] | None) -> list[str]:
    """Plan-store tools the given mapping does not provide.

    :param plan_tools: Session-bound tools keyed by name, or None.
    :return: Names that are missing; empty when the store is usable.
    """
    if not plan_tools:
        return list(_REQUIRED_PLAN_TOOLS)
    return [name for name in _REQUIRED_PLAN_TOOLS if name not in plan_tools]


async def _call_plan_tool(
    plan_tools: dict[str, Any], name: str, **kwargs: Any
) -> Any:
    """Call one plan-store tool, sync or async.

    The store is a plugin's plain function today, but a plugin is free to
    make it async later. Awaiting a non-awaitable raises ``TypeError``,
    which would surface as a failed plan rather than a contract problem,
    so this detects the shape instead of assuming one.

    :param plan_tools: Session-bound tools keyed by name.
    :param name: Tool to call.
    :param kwargs: Arguments for the tool.
    :return: The tool's return value.
    """
    import inspect

    result = plan_tools[name](**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _make_plan_task(plan_tools: dict[str, Any], read_tools: list[Any]) -> Any:
    """Build the ``plan_task`` delegate (the delegate writes the plan)."""

    async def _plan_task(description: str) -> str:
        """Decompose a task into an ordered step plan, stored as a todo.

        Runs the planner subagent, then records its steps in this
        session's todo list — the same list the user sees and can edit.
        Nothing is executed here.

        :param description: What needs doing, in plain language.
        :return: The plan's todo id and its steps, or an explicit failure
            message when the planner produced no usable plan.
        """
        from berg_agents.agents.planner import (
            PLANNER_PLAN_INSTRUCTIONS,
            PlannerDeps,
            build_planner_agent,
        )

        # The planner subagent is read-only: it gets the workspace's read
        # tools so it is not blind to the repo, and never the plan-store
        # tools. This delegate is the single writer of the plan into the
        # session's todo list — a planner with store tools created its
        # own todo, and the delegate then created a second from its text
        # output, so one plan arrived as two diverging todos.
        agent = build_planner_agent(
            plugin_tools=read_tools, instructions=PLANNER_PLAN_INSTRUCTIONS
        )
        # A plan is a short list, never an essay. Without a cap a looping
        # planner produced 65 MB of output, which then exceeded the
        # model's 50 MB request limit when the tool result was echoed
        # back - one bad planning run became a dead session.
        result = await agent.run(
            description,
            deps=PlannerDeps(),
            model_settings={"max_tokens": _MAX_PLAN_OUTPUT_TOKENS},
        )
        plan = str(result.output).strip()
        # Only enumerated lines become steps. If the planner wrote prose
        # and no list - including a refusal such as "I can't" - there is
        # no plan to store. Say so instead of creating an empty todo the
        # user has to clean up, and never let a refusal reach the
        # implementer as if it were a plan.
        steps = [
            s
            for s in _plan_steps_from_text(plan, limit=_MAX_PLAN_STEPS)
            if not _is_commentary(s)
        ]
        if not steps:
            return (
                "plan_task failed: the planner returned prose with no "
                "enumerated steps, so nothing was stored. Planner said:"
                f"\n{_excerpt(plan)}"
            )
        title = _plan_title(description)
        created = await _call_plan_tool(plan_tools, "create_todo", title=title)
        todo_id = _todo_id_from(created)
        if not todo_id:
            return (
                "plan_task failed: the plan could not be stored in the "
                f"todo list. Store said:\n{created}"
            )
        # Subtasks are the plan: one per enumerated step, in order.
        for step in steps:
            await _call_plan_tool(
                plan_tools, "add_subtask", todo_id=todo_id, text=step
            )
        return (
            f"Planned '{title}' as todo {todo_id} with "
            f"{len(steps)} steps. The user can edit this plan in the "
            "todo panel; read it back with list_subtasks and hand it to "
            "the implementation delegate with delegate_task.\n\n"
            + _excerpt(plan)
        )

    return _plan_task


def _plan_title(description: str) -> str:
    """A short, stable title for a plan stored from *description*.

    :param description: The user's task text.
    :return: First line, trimmed to a reasonable todo title length.
    """
    first = " ".join(description.strip().splitlines()[0].split())
    return (first[:80] or "Plan").rstrip(" .:")


def _todo_id_from(created: Any) -> str:
    """Extract the todo id from a ``create_todo`` response.

    :param created: Whatever the store returned (string or structured).
    :return: The id, or "" when it cannot be determined.
    """
    if isinstance(created, dict):
        for key in ("id", "todo_id", "todoId"):
            value = created.get(key)
            if value:
                return str(value)
        return ""
    text = str(created or "")
    # The store's human-readable line ends with "ID: <id>".
    marker = "ID:"
    if marker in text:
        tail = text.split(marker, 1)[1].strip()
        return tail.split()[0].strip("`'\"[]()") if tail else ""
    return ""


#: Hard cap on the planner's own output length, in tokens. A step plan
#: fits comfortably here; anything longer is a runaway generation, not a
#: plan.
_MAX_PLAN_OUTPUT_TOKENS = 2000

#: Hard cap on how many steps one plan may store. A plan with more steps
#: than this is not a plan a human will read - and a looping planner can
#: return megabytes, which then blew the model request limit when the
#: tool result was sent back.
_MAX_PLAN_STEPS = 50

#: Hard cap on characters of planner output echoed into a tool result.
#: Tool results are fed back to the model, so unbounded echoes turn one
#: bad planning run into a failed request (observed: 65 MB -> HTTP 413).
_MAX_ECHO_CHARS = 4000


def _excerpt(text: str, limit: int = _MAX_ECHO_CHARS) -> str:
    """Trim *text* for inclusion in a tool result.

    :param text: Text to echo back.
    :param limit: Maximum characters to keep.
    :return: The text, truncated with a note when it was longer.
    """
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return f"{text[:limit]}\n\n[... {dropped} more characters truncated]"


def _plan_steps_from_text(plan: str, limit: int = 0) -> list[str]:
    """Split a planner's output into ordered step strings.

    Only enumerations count as steps: ``1. ...``, ``1) ...``, ``- ...``,
    ``* ...``. Every other line - narration, headings, "here's what I
    did" preambles, trailing notes - is dropped.

    This is deliberately strict. An earlier version kept any non-empty
    line, so a planner that narrated ("The plan is in place...", "Two
    notes on what happened...") had that narration stored as plan steps
    the user then saw in the todo panel. The stored plan must contain
    steps and nothing else; prose belongs in the chat reply, which
    ``plan_task`` already returns.

    :param plan: The planner's raw output.
    :param limit: Stop after this many steps; 0 means no limit. A
        runaway planner can return a book, and both the write loop and
        the tool's return value must stay bounded.
    :return: Step texts in order; empty when nothing enumerates.
    """
    steps: list[str] = []
    for raw in plan.splitlines():
        if limit and len(steps) >= limit:
            # Stopping the scan is not enough: the caller often passes a
            # huge string, so fail fast instead of walking every line.
            break
        line = raw.strip()
        if not line:
            continue
        # Numbered item: "1. " / "1) " - but not a decimal like "50.5 ms".
        numbered = False
        for marker in (".", ")"):
            head, sep, rest = line.partition(marker)
            if sep and head.strip().isdigit() and rest[:1].isspace():
                # "50.5 ms" fails here: the character after "." is a digit.
                line = rest.strip()
                numbered = True
                break
        if not numbered:
            # Bullet item: "- " / "* ". Anything else is narration, a
            # heading, or a sign-off - never a step.
            if line[:2] in {"- ", "* "}:
                line = line[2:].strip()
            else:
                continue
        if not line or line.startswith("#"):
            continue
        steps.append(line)
    return steps


def _is_commentary(step: str) -> bool:
    """Whether *step* is the planner talking about the plan, not a step.

    A planner often ends with commentary written as list items - "Two
    notes on what happened:", "Complexity is low-to-moderate", "Step 6
    has no human review gate". Stored verbatim those appear in the todo
    panel as if they were work to do, which is exactly the kind of
    noise a user then has to clean up by hand.

    The test is about what the text *is*, not what words it uses: a
    step tells someone to do something. Commentary describes the plan,
    grades it, or refers to steps by number.

    :param step: One candidate step line, already un-marked.
    :return: True when the line is commentary and must not be stored.
    """
    lowered = step.lower().strip()
    if not lowered:
        return True
    # A clause that ends in ":" introduces the list that follows it. It is
    # a heading for sub-items, not work on its own - stored as a step it
    # reads "Define "stale" — Concrete, auditable criteria, e.g.:" with
    # nothing under it.
    if lowered.endswith(":"):
        return True
    # Declining to do the work is not a step. "Enable file access. Give me
    # a tool..." is the planner pushing back on the user; executing it
    # would ask a user to hand over tools mid-plan.
    refusal_markers = (
        "paste the",
        "give me",
        "i can't",
        "i cannot",
        "i don't have",
        "i do not have",
        "i'm unable",
        "i am unable",
        "enable file access",
        "file access",
        "no way to write",
        "don't have access",
        "you write it",
    )
    if any(marker in lowered for marker in refusal_markers):
        return True
    # Self-narration is first person: a step tells *you* to act ("Read the
    # README"), commentary reports what the planner did ("I first wrote
    # all four subtasks...", "Here's what I created").
    if re.match(r"^(i|we)\b|^(here'?s|here is|below)\b", lowered):
        return True
    # Meta-commentary that describes the plan rather than ordering work.
    meta_markers = (
        "what happened",
        "the plan is",
        "this plan",
        "complexity",
        "low-risk",
        "low risk",
        "straightforward",
        "no human review",
        "human review gate",
        "if you expected",
        "wasn't one",
        "not one",
        "consider adding",
    )
    if any(marker in lowered for marker in meta_markers):
        return True
    # "Step 6 has no review gate" - refers to another step by number and
    # therefore is about the plan, not an instruction of its own.
    return bool(re.search(r"\bstep[s]?\s+\d", lowered))


def _resolve_root(root_dir: str | Path) -> Path:
    return Path(root_dir).expanduser().resolve()


def create_tools(root_dir: str | Path = ".") -> list[ToolSpec]:  # ruff: ignore[complex-structure]
    """Return the default tool set as ToolSpecs.

    Wraps file ops with *root_dir* captured via closure so the model only
    sees ``file_path`` / ``content`` - not ``root_dir``.

    :param root_dir: Root directory file tools are bound to.
    :return: List of ToolSpec instances.
    """
    root = _resolve_root(root_dir)

    def _read(file_path: str) -> str:
        """Read a file relative to the workspace root.

        Returns a helpful message instead of raising when the
        path is a directory or does not exist, so the model
        can recover (e.g. by calling ``list_files``) instead
        of derailing into an error loop.

        :param file_path: Path to the file, may be /workspace-prefixed.
        """
        target = _normalize_target(file_path, root)
        if target.is_dir():
            return (
                f"{file_path} is a directory, not a file. "
                f"Call list_files with file_path={file_path!r} "
                f"to see its contents."
            )
        if not target.exists():
            return (
                f"File not found: {file_path}. "
                f"Call list_files on the parent directory to see "
                f"what exists."
            )
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {file_path}: {exc}"
        except UnicodeDecodeError:
            return f"Could not read {file_path}: not a UTF-8 text file."

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

    def _patch(file_path: str, old_text: str, new_text: str) -> str:
        """Replace one block of text inside an existing file.

        Surgical alternative to rewriting the whole file: only the
        first occurrence of ``old_text`` is replaced. Fails with
        guidance (instead of guessing) when the file is missing or
        the block is not found verbatim.

        :param file_path: Path to the file to patch.
        :param old_text: Exact text block to replace (verbatim).
        :param new_text: Replacement text.
        """
        target = _normalize_target(file_path, root)
        if target.is_dir():
            return (
                f"{file_path} is a directory, not a file. "
                f"Call list_files with file_path={file_path!r} "
                f"to see its contents."
            )
        if not target.exists():
            return (
                f"File not found: {file_path}. "
                f"Call list_files on the parent directory to see "
                f"what exists."
            )
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {file_path}: {exc}"
        except UnicodeDecodeError:
            return f"Could not read {file_path}: not a UTF-8 text file."
        if old_text not in text:
            return (
                f"Block not found verbatim in {file_path}. "
                f"Call read_file first and copy the exact text, "
                f"whitespace included."
            )
        remaining = text.count(old_text) - 1
        _atomic_write(target, text.replace(old_text, new_text, 1))
        note = (
            f" ({remaining} identical block(s) left untouched)"
            if remaining
            else ""
        )
        return f"Patched {file_path}{note}"

    def _list(file_path: str = ".") -> str:
        """List files and subdirectories in a workspace directory.

        Use this to explore the project layout before reading
        files - never guess at paths. Directories end with "/".
        Results are sorted, directories first, capped at 200
        entries to keep the context small.

        :param file_path: Directory to list, relative to the
            workspace root (default: the root itself).
        """
        target = _normalize_target(file_path, root)
        if not target.exists():
            return (
                f"Directory not found: {file_path}. "
                f"Call list_files with file_path='.' to start "
                f"from the workspace root."
            )
        if not target.is_dir():
            return (
                f"{file_path} is a file, not a directory. "
                f"Call read_file to see its contents."
            )
        try:
            entries = sorted(
                target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError as exc:
            return f"Could not list {file_path}: {exc}"
        lines = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:200]]
        extra = (
            f"\n... and {len(entries) - 200} more (listing truncated)"
            if len(entries) > 200
            else ""
        )
        return "\n".join(lines) + extra if lines else "(empty directory)"

    def _bash(command: str, timeout: int = 30) -> str:
        """Run a shell command in the workspace root.

        Use this to run tests, builds, linters, or inspect the
        system (e.g. ``pytest -q``, ``ls``, ``python --version``).
        There is no other shell/terminal tool - this is it.

        Safety: commands run with ``cwd`` bound to the workspace
        root, a timeout (default 30s, capped at 120s), and output
        truncated at 8000 characters. Every invocation is logged.

        :param command: Shell command to run (via ``bash -c``).
        :param timeout: Seconds before the command is killed.
        """
        import logging
        import subprocess

        try:
            clamped = max(1, min(int(timeout), 120))
        except (TypeError, ValueError):
            clamped = 30
        logging.getLogger(__name__).warning("bash tool: %s", command)
        try:
            proc = subprocess.run(
                command,
                check=False,
                shell=True,
                executable="/bin/bash",
                cwd=root,
                capture_output=True,
                text=True,
                timeout=clamped,
            )
        except subprocess.TimeoutExpired:
            return (
                f"Command timed out after {clamped}s and was killed: {command}"
            )
        except OSError as exc:
            return f"Could not run command: {exc}"
        combined = (proc.stdout or "") + (
            f"\n[stderr]\n{proc.stderr}" if proc.stderr else ""
        )
        if len(combined) > 8000:
            combined = (
                combined[:8000] + f"\n... output truncated "
                f"({len(combined)} chars total)"
            )
        return f"[exit {proc.returncode}]\n{combined}".strip()

    def _search(pattern: str, directory: str = ".") -> str:
        """Search file contents under a workspace directory.

        Recursive literal-match grep over text files. Use this to
        find references, definitions, or error strings instead of
        guessing file paths. Binary files, hidden directories
        (``.git``, ``node_modules``, ``__pycache__``, ``.venv``),
        and files over 1MB are skipped. Results capped at 50 hits.

        :param pattern: Literal text to search for (not a regex).
        :param directory: Where to search, relative to the
            workspace root (default: the root itself).
        """
        base = _normalize_target(directory, root)
        if not base.exists():
            return (
                f"Directory not found: {directory}. "
                f"Call list_files with file_path='.' to start "
                f"from the workspace root."
            )
        if not base.is_dir():
            return (
                f"{directory} is a file, not a directory. "
                f"Call read_file to see its contents."
            )
        skip_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            ".next",
            "dist",
            ".turbo"}
        hits: list[str] = []
        scanned = 0
        for path in sorted(base.rglob("*")):
            if len(hits) >= 50:
                break
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            scanned += 1
            if scanned > 2000:
                break
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    rel = path.relative_to(root)
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 50:
                        break
        if not hits:
            return f"No matches for {pattern!r} under {directory}."
        extra = (
            "\n... and more (results truncated at 50)"
            if len(hits) >= 50
            else ""
        )
        return "\n".join(hits) + extra

    return [
        make_tool_spec(_list, name="list_files", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_read, name="read_file", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_search, name="search_code", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_bash, name="bash", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_edit, name="edit_file", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_patch, name="patch_file", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_write, name="write_file", risk_class="high"),  # type: ignore[arg-type]
    ]
