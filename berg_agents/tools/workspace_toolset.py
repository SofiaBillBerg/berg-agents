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

The file tools are the harness's, not berg's: a
:class:`~pydantic_ai_harness.FileSystem` toolset (ripgrep-backed grep,
containment to ``root_dir``, ``.git``/``.env``/secrets protected by
default, content hashes and optimistic-concurrency writes) wrapped here
for what berg adds on top, following the documented custom-toolset
pattern (subclass :class:`~pydantic_ai.toolsets.WrapperToolset`,
override the extension points you need, delegate the rest):

- One stable ``id`` (``"workspace"``) identifying every instruction
  and tool the workspace contributes - addressable as
  ``toolset:workspace`` and safe for durable execution.
- One ``get_instructions`` block teaching explore-first usage in the
  harness tools' own terms (regex-vs-literal grep, hashes, exact-string
  edits), instead of repeating usage guidance per tool and in the prompt.
- Selective approval: the mutating tools (``write_file``,
  ``edit_file``, ``create_directory``) pause for the user through the
  framework's own ``approval_required``, so berg's HITL surface stays
  the one pydantic-ai already drives for the chat approval cards.
- Dynamic membership: ``read_only`` / ``allow_shell`` constructor flags
  select the registered subset per deployment, and ``call_tool`` is
  the single audit/logging switch for every invocation.
- The two tools berg still owns alongside it: ``plan_task`` (the
  staged delegate that writes the plan into the session's todo list)
  and the ``run_command`` bridge - berg's one shell function until the
  Shell capability replaces it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.wrapper import WrapperToolset
from pydantic_ai_harness import FileSystem

if TYPE_CHECKING:
    from berg_agents.tools.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

#: Cap on one command's combined output. A command that prints more is
#: truncated with a note rather than flooding the model's context.
_MAX_OUTPUT_CHARS = 8000

#: The workspace tools whose calls pause for the user's approval. Reads,
#: searches and listings run unattended; anything that changes the tree
#: does not. Names, not risk classes: the harness's toolset is the source
#: of the membership, and this is the gate berg puts on it.
_APPROVAL_TOOLS: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "create_directory"})


def _needs_approval(ctx: Any, tool_def: Any, tool_args: Any) -> bool:
    """Whether one workspace call must wait for Sofia's decision.

    The predicate the framework's ApprovalRequiredToolset calls per tool
    call. Only the mutating tools answer yes — a search or a read that
    paused for approval would make the agent unusable, and a write that
    did not would be the "AI running loose" this exists to prevent.

    :param ctx: The run context (unused — the policy is per tool name).
    :param tool_def: The tool definition about to run.
    :param tool_args: Its arguments (unused — the policy is per tool).
    :return: True when the call pauses for approval.
    """
    _ = ctx, tool_args
    return tool_def.name in _APPROVAL_TOOLS


def run_command_tool(root_dir: str | Path) -> Any:
    """Berg's one shell function, bound to *root_dir*.

    The bridge: the harness's Shell capability is the eventual home for
    command execution, but its ``run_command`` needs a run context this
    route/toolset level does not have, and until it lands there must be
    exactly one shell implementation, not two. This is that one — the
    same body the ``/api/tool/execute`` seam serves.

    :param root_dir: The workspace root the command runs in.
    :return: The ``run_command`` tool function.
    """
    import subprocess

    def run_command(command: str, timeout: int = 30) -> str:
        """Run a shell command in the workspace root.

        Use this to run tests, builds, linters, or inspect the system
        (e.g. ``pytest -q``, ``ls``, ``python --version``). There is no
        other shell/terminal tool - this is it.

        Paths: relative paths resolve from the workspace root. A
        ``/workspace/...`` spelling — the mount name older prompts
        advertised — is rewritten to the root, because there is no
        ``/workspace`` on disk and the command would otherwise read a
        path that does not exist.

        Safety: commands run with ``cwd`` bound to the workspace root, a
        timeout (default 30s, capped at 120s), and output truncated at
        8000 characters. Every invocation is logged.

        :param command: Shell command to run (via ``bash -c``).
        :param timeout: Seconds before the command is killed.
        """
        # The mount name is not a real path here; rewrite it rather than
        # run a command against a directory that does not exist.
        root = str(root_dir)
        command = command.replace("/workspace/", f"{root.rstrip('/')}/")
        try:
            clamped = max(1, min(int(timeout), 120))
        except (TypeError, ValueError):
            clamped = 30
        logging.getLogger(__name__).warning("run_command tool: %s", command)
        try:
            proc = subprocess.run(
                command,
                check=False,
                shell=True,
                executable="/bin/bash",
                cwd=str(root_dir),
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
        if len(combined) > _MAX_OUTPUT_CHARS:
            combined = (
                combined[:_MAX_OUTPUT_CHARS] + f"\n... output truncated "
                f"({len(combined)} chars total)"
            )
        return f"[exit {proc.returncode}]\n{combined}".strip()

    return run_command


#: Stable toolset id for berg's STAGED tools (the run_command bridge and
#: the plan_task delegate). Instruction parts and durable-execution
#: records key off this string, so keep it constant. The file tools
#: answer to the capability's own id (``workspace``, set on
#: :class:`WorkspaceFileSystem`) — one id per surface, no sharing.
STAGED_TOOLSET_ID = "workspace_staged"

#: Usage guide injected into the agent's instructions once per run.
#: Complements (not replaces) the system prompt's authoritative tool
#: list: this text teaches *how* to work the filesystem, the prompt
#: names *what* exists.
_WORKSPACE_INSTRUCTIONS = """\
Workspace tools (toolset `workspace`) - how to work the filesystem:

- EXPLORE FIRST: call list_directory before reading anything. Never guess
  at paths; use the exact paths list_directory returns.
- Directories are not files: read_file on a directory says so - follow
  its guidance instead of retrying.
- SEARCH before assuming: use grep to find definitions, references, or
  error strings instead of reading trees by hand. grep is ripgrep: its
  pattern is a REGEX unless you pass literal=True. For plain text (a
  name, an error string) pass literal=True, and narrow with path= and
  glob= instead of searching the whole tree.
- RUN things with run_command (tests, builds, inspection). It has a
  timeout and truncated output; long jobs should be split or
  backgrounded by the caller. There is no other shell tool.
- WRITE with intent: write_file replaces a whole file; edit_file
  replaces one exact block - old_text must appear verbatim, exactly
  once, or the edit is refused with guidance. Both need human approval
  in chat - the user sees an approve/reject dialog, so say what you are
  about to do before calling.
- read_file answers with line numbers and a content hash, and writes
  return the new hash. Pass expected_hash to a write when you read the
  file earlier and must not overwrite a change made since.
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


def workspace_file_tools(read_only: bool = False) -> list[str]:
    """The file tools berg offers, in the order the model should reach.

    The harness registers ten; berg keeps the classic five — the surface
    its agents always had — so a small local model is not handed more
    tools to choose between. In read-only mode the harness's own
    ``READ_ONLY_TOOL_NAMES`` intersects the selection, so neither the
    tools nor the derived prompt inventory can offer a write the agent
    does not have.

    :param read_only: Whether the agent may not write at all.
    :return: The tool names, in the order to register them.
    """
    from pydantic_ai_harness.filesystem import READ_ONLY_TOOL_NAMES

    selected = [
        "read_file",
        "write_file",
        "edit_file",
        "list_directory",
        "grep"]
    if read_only:
        selected = [t for t in selected if t in READ_ONLY_TOOL_NAMES]
    return selected


class WorkspaceFileSystem(FileSystem):
    """The harness's FileSystem as a CAPABILITY, with berg's gate on writes.

    Registered through ``capabilities=``, never ``toolsets=``: the
    harness's file tools emit capability events (``FileReadEvent``,
    ``FileWrittenEvent``, ``DirectoryListedEvent`` ...), and pydantic-ai
    accepts those only from tools a CAPABILITY contributes — a plain
    toolset is refused at call time, which is how the first iteration of
    this integration failed.

    The approval wrapper rides the toolset the capability hands the
    framework: writes pause for Sofia, reads and searches do not, and the
    gate is the framework's own (``ApprovalRequiredToolset``), so those
    calls land in the same ``DeferredToolRequests`` batch the chat
    approval cards and the auto-approve opt-in already speak — one HITL
    surface, not a second one.
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        read_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Berg's file-tool capability: root, tools, id and instructions.

        Defaults carry berg's whole workspace policy in one place — the
        stable id, the usage instructions the model reads, and the tool
        selection — so a caller says only WHERE the workspace is.

        :param root_dir: Containment boundary for every file tool.
        :param read_only: When True, the mutating tools are absent.
        :param kwargs: Any other FileSystem argument (denied_patterns,
            max_read_chars, ...), passed through untouched.
        """
        kwargs.setdefault("id", "workspace")
        kwargs.setdefault("description", _WORKSPACE_INSTRUCTIONS)
        kwargs.setdefault("tools", workspace_file_tools(read_only))
        super().__init__(root_dir, read_only=read_only, **kwargs)

    def get_toolset(self) -> Any:
        """The capability's toolset, writes gated unless read-only.

        :return: The file toolset, wrapped in the approval gate when the
            agent may write.
        """
        toolset = super().get_toolset()
        if self.read_only:
            # Nothing to gate: the mutating tools are not registered.
            return toolset
        return toolset.approval_required(approval_required_func=_needs_approval)


class WorkspaceToolset(WrapperToolset[None]):
    """Berg's staged workspace tools as one named toolset.

    The FILE tools are the harness's, registered as the
    :class:`WorkspaceFileSystem` capability beside this toolset (they
    emit capability events, which only a capability may contribute).
    What remains here is what berg still owns: the ``run_command``
    bridge — the one shell function until the Shell capability lands —
    and the staged ``plan_task`` delegate, plus the stable toolset id,
    the usage instructions, and the audited call path over both.

    :param root_dir: Workspace root the bridge and delegate act in.
    :param read_only: When True, the staged tools are withheld with the
        mutating file tools — a read-only agent gets neither.
    :param allow_shell: When False, the ``run_command`` tool is withheld
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
        """Initialize the staged-tools toolset.

        :param root_dir: Workspace root the bridge and delegate act in.
        :param read_only: When True, the staged tools are withheld with
            the mutating file tools — a read-only agent gets neither.
        :param allow_shell: When False, the ``run_command`` tool is
            withheld (safe default for untrusted deployments).
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
        extra: FunctionToolset[None] = FunctionToolset()
        if allow_shell and not read_only:
            extra.add_function(
                run_command_tool(root_dir),
                name="run_command",
                description=(
                    "Run a shell command in the workspace root (tests, "
                    "builds, linters, inspection). Bounded timeout, "
                    "truncated output."
                ),
                requires_approval=True,
            )
        # The planner subagent's read-only tools: it may ground a plan in
        # the repo it plans for, but the plan itself is written by the
        # plan_task delegate alone. Store write tools are withheld on
        # purpose — a planner with store tools created its own todo, and
        # the delegate then created a second from its text output.
        # The planner subagent now reads through the harness's file
        # tools like everything else (read_only at its own capability),
        # so nothing but the workspace root is handed over.
        missing = _missing_plan_tools(plan_tools)
        if not read_only and not missing and plan_tools is not None:
            # Staged delegation over ONE plan store: plan_task writes the
            # plan into the session's todo list, and the delegate reads it
            # back by id. The user sees and edits that same list, so the
            # views never diverge.
            extra.add_function(
                _make_plan_task(plan_tools, root_dir),
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
        super().__init__(wrapped=extra)
        self._root_dir = str(root_dir)

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any
    ) -> Any:
        """Audit-log every staged-tool invocation, then run it.

        The single audit switch for the tools berg still owns here
        (``run_command`` bridge, ``plan_task``); the file tools are
        audited by the harness's own events on the capability side.

        :param name: The tool to run.
        :param tool_args: Its arguments.
        :param ctx: Context from the agent.
        :param tool: The tool as the framework resolved it.
        :return: The tool's result.
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

    def inventory_specs(self) -> list[ToolSpec]:
        """The staged tools as specs for the prompt inventory.

        DERIVED from the toolset the agent is built with (see
        :func:`~berg_agents.tools.tool_spec.specs_from_toolset`), so the
        prompt cannot name a parameter these tools reject. The file
        tools contribute their own specs from the capability side.

        :return: The specs.
        """
        from berg_agents.tools.tool_spec import specs_from_toolset

        return specs_from_toolset(self.wrapped)

    @property
    def id(self) -> str | None:
        """Stable toolset id for berg's staged tools (``"workspace_staged"``).

        The workspace's FILE tools answer to the capability's id
        (``"workspace"``, set on :class:`WorkspaceFileSystem`); this one
        identifies the bridge and the delegate.

        :return: Toolset id.
        """
        return STAGED_TOOLSET_ID

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


def _run_planner_sync(root_dir: str | Path, description: str) -> str:
    """Run the planner subagent OUTSIDE the caller's run, in its own loop.

    A nested ``agent.run()`` inside a tool hangs when the child carries
    capability-emitting tools: the child's events try to reach a run the
    parent is still blocked on (found by isolating the plan_task hang —
    the same code nested inline never returned; the same code here does,
    in about a minute). Running it on a bare executor thread gives the
    planner a run context of its own, which is the only thing its
    capability events need.

    :param root_dir: The workspace the planner reads.
    :param description: What to plan.
    :return: The planner's raw output, stripped.
    """
    from berg_agents.agents.planner import PlannerDeps, build_planner_agent

    async def _go() -> str:
        planner = build_planner_agent(root_dir=root_dir)
        result = await planner.run(
            description,
            deps=PlannerDeps(),
            model_settings={"max_tokens": _MAX_PLAN_OUTPUT_TOKENS},
        )
        return str(result.output).strip()

    return asyncio.run(_go())


def _make_plan_task(plan_tools: dict[str, Any], root_dir: str | Path) -> Any:
    """Build the ``plan_task`` delegate (the delegate writes the plan).

    :param plan_tools: The session-bound plan-store tools the delegate
        writes the plan through.
    :param root_dir: The workspace the planner subagent reads.
    :return: The ``plan_task`` tool function.
    """

    async def _plan_task(description: str) -> str:
        """Decompose a task into an ordered step plan, stored as a todo.

        Runs the planner subagent, then records its steps in this
        session's todo list — the same list the user sees and can edit.
        Nothing is executed here.

        :param description: What needs doing, in plain language.
        :return: The plan's todo id and its steps, or an explicit failure
            message when the planner produced no usable plan.
        """
        # The planner subagent is read-only by construction (its
        # WorkspaceFileSystem is read_only), and it reads the SAME
        # workspace this toolset serves. This delegate is the single
        # writer of the plan into the session's todo list — a planner
        # with store tools created its own todo, and the delegate then
        # created a second from its text output, so one plan arrived as
        # two diverging todos. It runs on its own thread (see
        # _run_planner_sync), not nested in this run.
        # A plan is a short list, never an essay. Without a cap a looping
        # planner produced 65 MB of output, which then exceeded the
        # model's 50 MB request limit when the tool result was echoed
        # back - one bad planning run became a dead session.
        # On an executor thread, not awaited inline: the nested run's
        # capability events need a run context of their own (see
        # _run_planner_sync).
        loop = asyncio.get_running_loop()
        plan = await loop.run_in_executor(
            None, _run_planner_sync, root_dir, description
        )
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
