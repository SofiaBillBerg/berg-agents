# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
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

Wraps the framework-free :class:`~berg_agents.core.tool_spec.ToolSpec`
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
  plan panel the user can see and edit). Then implement_task runs the
  plan by its id. Each stage streams its own result — progress stays
  visible.
- The todo list IS the plan. If the user edits it, that edited version
  is what implement_task executes — never re-plan over their changes.
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
    the harness loop and ``/api/tool/execute`` run) plus staged
    ``plan_task`` / ``implement_task`` subagent delegates, then adds
    identity, instructions, dynamic membership, and an audited call
    path on top.

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
        from berg_agents.agents.factory import create_tools
        from pydantic_ai.toolsets import FunctionToolset

        # Sink for subagent progress, set by the web layer once the run
        # exists (the run is created after the agent, so this cannot be a
        # constructor argument). A holder dict rather than a plain
        # attribute: the delegate reads it at call time, so it always sees
        # the sink attached to the run that is currently streaming. No
        # sink means "nothing is watching" - a CLI or harness caller
        # simply gets no progress relay.
        self.progress_holder: dict[str, Any] = {"sink": None}
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
            # plan into the session's todo list, implement_task reads it
            # back by id. The human sees and edits that same list, so the
            # three views never diverge.
            inner.add_function(
                _make_plan_task(plan_tools, read_tools),
                name="plan_task",
                description=(
                    "Decompose a task into an ordered step plan and write "
                    "it to this session's todo list. Returns the plan's "
                    "id, which implement_task consumes."
                ),
                requires_approval=False,
                timeout=240.0,
            )
            inner.add_function(
                _make_implement_task(
                    str(root_dir), plan_tools, self.progress_holder
                ),
                takes_ctx=True,
                name="implement_task",
                description=(
                    "Execute a plan from this session's todo list, by id, "
                    "via the implementation subagent (workspace-rooted "
                    "file tools). Reads the list as the user left it."
                ),
                # No timeout: the subagent is a real run that keeps writing
                # after the tool call returns, so a cap reported failure over
                # live work. Stop is the way to end it.
                requires_approval=True,
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


async def _resolve_todo_id(
    plan_tools: dict[str, Any], todo_id: str
) -> tuple[str | None, list[str]]:
    """Resolve a possibly truncated todo id against the store.

    Models re-type ids between stages and routinely drop edge
    characters (observed: a 50-char slug ending in ``"alpha",`` was
    sent twice without the trailing comma, and an exact-only lookup
    misdiagnosed it as "no steps to execute"). Exact match wins;
    failing that, a single unique prefix match is accepted in either
    direction — the model usually *drops* characters (its id is then a
    prefix of the stored one), but the stored id can also be the
    prefix if it was truncated at creation. Anything ambiguous is left
    unresolved with the full id list, so the caller can point the
    model at the real id instead of guessing.

    :param plan_tools: Session-bound tools keyed by name.
    :param todo_id: The id as the model typed it.
    :return: ``(resolved id or None, all stored todo ids)``.
    """
    available: list[str] = []
    if "list_todo_items" not in plan_tools:
        # Store without the structured listing (older plugin): exact
        # match is all that can be checked.
        return todo_id, available
    try:
        items = await _call_plan_tool(plan_tools, "list_todo_items")
    except Exception as exc:
        # A broken listing must not kill the exact-match path: fall
        # back to treating the typed id as authoritative.
        logger.warning("todo id resolution failed: %s", exc)
        return todo_id, available
    for item in items or []:
        item_id = str(item.get("id") or "")
        if item_id:
            available.append(item_id)
    if todo_id in available:
        return todo_id, available
    candidates = [
        stored
        for stored in available
        if stored.startswith(todo_id) or todo_id.startswith(stored)
    ]
    if len(candidates) == 1:
        logger.info(
            "todo id %r resolved by unique prefix to %r", todo_id, candidates[0]
        )
        return candidates[0], available
    return None, available


def _brief(value: Any, limit: int = 160) -> str:
    """Collapse a tool argument or result into one short log line.

    The subagent's progress notes ride the chat's own SSE stream, so a
    full file body or a 200-line bash result would flood the transcript.
    This keeps the *shape* of the activity (which tool, on what) without
    the payload.

    :param value: Any tool argument or result.
    :param limit: Maximum characters kept.
    :return: Single-line, truncated text.
    """
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _brief_args(args: Any) -> str:
    """Render a tool call's arguments compactly for a progress note.

    :param args: The call's arguments (mapping, string, or None).
    :return: ``key=value`` pairs, or a plain string, clipped for display.
    """
    if isinstance(args, dict):
        pairs = [f"{key}={_brief(val, 60)}" for key, val in args.items()]
        return _brief(", ".join(pairs))
    return _brief("" if args is None else args)


def _plan_items_to_text(items: list[dict[str, Any]], title: str) -> str:
    """Render stored plan items as the step list an implementer reads.

    Completed steps stay in the list, marked done: the implementer needs
    to know what is already finished, and dropping them would let it redo
    work the user already checked off. Each line carries the step's store
    index, which is what ``set_subtask_done`` takes - without it the
    implementer could not check progress off even when told to.

    :param items: Subtask dicts from the store, in order.
    :param title: The plan's title, used as a heading.
    :return: A Markdown step list; empty string when there are no items.
    """
    lines: list[str] = []
    for position, item in enumerate(items):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        done = str(item.get("status") or "") == "done"
        # Prefer the store's own index: it is the key set_subtask_done
        # resolves, and a skipped blank subtask would shift a
        # position-based number away from it.
        index = item.get("index", position)
        lines.append(f"[{index}] {'[done] ' if done else ''}{text}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        f"Plan: {title}\n"
        f"Todo id (use as todo_id): {title}\n\n{body}\n\n"
        "Check each step off with set_subtask_done(todo_id, index) as you "
        "finish it. Steps marked [done] are already finished — do not redo them."
    )


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
            "todo panel; implement_task runs it as it stands.\n\n"
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
    noise a human then has to clean up by hand.

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
    # would ask a human to hand over tools mid-plan.
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


def _make_implement_task(
    root_dir: str,
    plan_tools: dict[str, Any],
    sink_owner: dict[str, Any] | None = None,
) -> Any:
    """Build the ``implement_task`` delegate (reads the stored plan).

    :param root_dir: Workspace root the implementer's file tools are bound to.
    :param plan_tools: Session-bound plan-store tools.
    :param sink_owner: Mutable holder whose ``"sink"`` entry is read at
        call time. The web layer sets it once the run exists (the run is
        built after the agent), so a captured value would always be the
        stale ``None``.
    """

    async def _implement_task(
        ctx: RunContext[Any], todo_id: str, task_type: str = "generic"
    ) -> str:
        """Execute a stored step plan via the implementation subagent.

        Reads the plan from this session's todo list at call time, so a
        plan the user edited is the plan that runs. Reports what was
        actually written. Execution needs human approval first.

        :param ctx: Parent run context - carries the sink that relays the
            subagent's activity to the web UI.
        :param todo_id: Id of the todo whose subtasks form the plan.
            Resolved exactly first, then by unique prefix, so a re-typed
            id that lost edge punctuation still finds the plan; when
            several or no todos match, the real ids are reported back
            instead of a guess.
        :param task_type: Task type label for model routing.
        :return: Execution summary naming the files really changed.
        """
        from berg_agents.agents.implementation import (
            ImplementationDeps,
            build_implementation_agent,
            summarize_changes,
        )

        # Resolve the id the model typed: exact first, then unique
        # prefix. The model re-types ids between stages and drops edge
        # punctuation (one plan id lost its trailing comma twice in a
        # single session); an exact-only lookup turned that into "no
        # steps to execute" — the wrong diagnosis for a wrong id.
        typed_id = todo_id.strip()
        resolved, available = await _resolve_todo_id(plan_tools, typed_id)
        if resolved is None:
            listing = ", ".join(available) if available else "(no todos stored)"
            return (
                f"implement_task: no todo matches the id {typed_id!r}. "
                f"Available todo ids: {listing}. Call again with one of them."
            )
        todo_id = resolved

        # Read the plan from the store at call time: a subtask the user
        # added, reworded, or checked off between planning and executing
        # is part of the plan that runs.
        steps = await _call_plan_tool(
            plan_tools, "list_subtasks", todo_id=todo_id
        )
        if not steps:
            return (
                f"implement_task: todo {todo_id} has no steps to execute. "
                "Plan first with plan_task, or add subtasks to the todo."
            )
        plan_text = _plan_items_to_text(steps, todo_id)
        if not plan_text:
            return (
                f"implement_task: todo {todo_id} has no readable steps. "
                "Add subtasks to the todo and try again."
            )
        completed = [i for i in steps if str(i.get("status")) == "done"]
        if completed and len(completed) == len(steps):
            return f"implement_task: every step of {todo_id} is already done."

        # Same session-bound store tools: the implementer can check off a
        # step as it finishes, so the panel reflects real progress rather
        # than the model's narration.
        agent = build_implementation_agent(
            plugin_tools=list(plan_tools.values())
        )
        deps = ImplementationDeps(workspace_root=root_dir, task_type=task_type)

        # Live progress: forward each tool call the implementer makes into
        # the parent run's journal. Without this the web UI showed the chat
        # model "Thinking…" for the whole subagent run and the activity was
        # only visible in the provider log. Read from the holder at call
        # time: the sink is attached by the web layer after this delegate
        # is built.
        reporter = (sink_owner or {}).get("sink")

        async def _on_event(_sub_ctx: Any, event_stream: Any) -> None:
            """Relay the implementer's tool activity to the parent run.

            :param _sub_ctx: The subagent's own run context (unused here;
                the parent sink must be the one that journals).
            :param event_stream: The subagent's native event stream.
            """
            from pydantic_ai import (
                FunctionToolCallEvent,
                FunctionToolResultEvent,
            )

            async for event in event_stream:
                if reporter is None:
                    continue
                if isinstance(event, FunctionToolCallEvent):
                    part = event.part
                    args = _brief_args(part.args)
                    reporter(f"step: {part.tool_name}({args})")
                elif isinstance(event, FunctionToolResultEvent):
                    content = str(getattr(event.part, "content", ""))
                    reporter(f"done: {event.tool_call_id} → {_brief(content)}")

        # No timeout: the old 600 s cap returned "Timed out" to the model
        # while the subagent kept working, so the UI reported failure over a
        # run that was still writing files. Ending the run is now the human's
        # explicit Stop (which cancels the parent, and with it this call).
        result = await agent.run(
            plan_text, deps=deps, event_stream_handler=_on_event
        )
        # The model's own text is narration: it can say "Task completed"
        # while having written nothing, or to a path it invented. Report
        # from the run's recorded writes so the caller (and the human
        # reading the chat) sees what actually happened on disk.
        summary = summarize_changes(deps.changes)
        narration = str(result.output).strip()
        if not deps.changes:
            return (
                f"{summary}\n\nThe implementation agent reported:\n{narration}"
            )
        return f"{summary}\n\nAgent report:\n{narration}"

    return _implement_task
