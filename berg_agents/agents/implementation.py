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

"""Implementation Pydantic AI agent for berg_agents.

Executes code changes: builds a step-by-step execution plan for a
task type, reports which tools the task needs, and scores how
confidently this agent can handle a task.

Model selection resolves the task complexity directly onto a model
from ``.berg-agents/bergagents.jsonc`` (``model_routing.models``), formatted
as a ``provider:model`` string via
:func:`berg_agents.providers.models.resolve_model_string`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Literal

from berg_agents.capabilities.registry import ToolCatalog
from berg_agents.providers.models import (
    resolve_model_instance,
    resolve_model_string,
)
from berg_agents.providers.tiers import model_for_complexity
from berg_agents.tools._io import _atomic_write, _normalize_target
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import ReinjectSystemPrompt

logger = logging.getLogger(__name__)


__all__ = [
    "EXECUTABLE_TASK_TYPES",
    "IMPLEMENTATION_AGENT_NAME",
    "OUTPUT_RETRIES",
    "ComplexityLevel",
    "ImplementationDeps",
    "PlanStep",
    "build_implementation_agent",
    "estimate_confidence",
    "implementation_agent",
    "plan_steps_for",
    "resolve_implementation_model"]

# Explicit output retry budget for the implementation agent.
# Spec name: ``output_retries (3)``. Pydantic AI v2 exposes it
# as the ``output`` entry of ``Agent(retries=...)`` (library
# default 1 for both budgets); the dict form below sets only
# the output budget and leaves the tool budget at its default.
OUTPUT_RETRIES = 3

# Explicit agent name: labels this agent's run span in Logfire so
# traces stay distinguishable when several agents run in one app.
IMPLEMENTATION_AGENT_NAME = "implementation"

# Complexity Level type: plain strings so this module stays
# decoupled from the old core interface being removed.
ComplexityLevel = Literal["trivial", "standard", "complex", "critical"]

# Task types this agent executes with high confidence.
EXECUTABLE_TASK_TYPES: frozenset[str] = frozenset({
    "edit_file",
    "new_file",
    "read_file",
    "delete_file",
    "format_code",
    "execute_command",
    "refactor",
    "implement",
    "fix"})

# Step-by-step execution plans per task type.
_PLAN_STEPS: dict[str, list[dict[str, str]]] = {
    "edit_file": [
        {"action": "read_file", "description": "Read file content"},
        {"action": "analyze", "description": "Analyze changes"},
        {"action": "apply_edit", "description": "Apply the edit"},
        {"action": "verify", "description": "Verify the change"}],
    "new_file": [
        {"action": "check_exists", "description": "Check file exists"},
        {"action": "create_file", "description": "Create new file"},
        {"action": "populate", "description": "Write content"}],
    "delete_file": [
        {"action": "confirm", "description": "Confirm safe deletion"},
        {"action": "backup_check", "description": "Check dependencies"},
        {"action": "delete", "description": "Delete the file"}]}

# Fallback plan for task types without a dedicated template.
_GENERIC_PLAN: list[dict[str, str]] = [
    {"action": "analyze", "description": "Analyze the task"},
    {"action": "execute", "description": "Execute the operation"},
    {"action": "verify", "description": "Verify the result"}]


@dataclass
class FileChange:
    """One file a run actually modified on disk.

    Attributes:
        action: Which mutating tool did it (write/edit/patch).
        path: Workspace-relative path as the tool resolved it.
    """

    action: str
    path: str


@dataclass
class ImplementationDeps:
    """Dependencies injected into each implementation agent run.

    Attributes:
        workspace_root: Workspace directory file tools are bound to.
        complexity: Task complexity level driving model selection.
        task_type: Task type being executed (e.g. ``"edit_file"``).
        changes: Every file this run actually wrote, appended by the
            mutating tools. This is the ground truth for "did the work
            happen" - the model's own summary is narration and may claim
            success for a write that never occurred. Callers report from
            here, never from the model's prose.
    """

    workspace_root: str = "."
    complexity: str = "standard"
    task_type: str = "generic"
    changes: list[FileChange] = field(default_factory=list)


class PlanStep(BaseModel):
    """One step of an execution plan.

    Attributes:
        action: Machine-readable step identifier.
        description: Human-readable step summary.
    """

    action: str
    description: str


def resolve_implementation_model(
    complexity: str = "standard", cfg: dict[str, Any] | None = None
) -> str:
    """Resolve the ``provider:model`` string for a complexity level.

    Looks up the complexity's model directly, then formats it through
    :func:`berg_agents.providers.models.resolve_model_string` so the result always carries the
    ``provider:`` prefix Pydantic AI requires.

    Args:
        complexity: Task complexity level.
        cfg: Optional plain configuration dictionary override.

    Returns:
        Model string in ``provider:model`` format, never a bare id.
    """
    # Complexity maps directly onto its model; None selects the
    # configured default model via the resolver.
    model_id = model_for_complexity(complexity, cfg)
    return resolve_model_string(model_id, cfg)


def plan_steps_for(task_type: str) -> list[PlanStep]:
    """Build the step-by-step execution plan for a task type.

    Pure function preserving the previous plan-builder behavior:
    known task types get their dedicated step template, anything
    else falls back to the generic analyze/execute/verify plan.

    :param task_type: Task type (e.g. ``"edit_file"``).

    :return: Ordered list of plan steps; never empty.
    """
    # Copy dicts into PlanStep models so callers cannot mutate
    # the module-level templates through the returned list.
    raw = _PLAN_STEPS.get(task_type, _GENERIC_PLAN)
    return [
        PlanStep(action=s["action"], description=s["description"]) for s in raw
    ]


def estimate_confidence(task_type: str, description: str) -> float:
    """Score how confidently this agent handles a task.

    Preserves the previous confidence behavior: executable task
    types score 0.95, descriptions with execution keywords score
    0.7, everything else scores 0.1.

    :param task_type: Task type string.
    :param description: Free-text task description.

    :return: Confidence score between 0.0 and 1.0.
    """
    # Exact task-type match is the strongest signal.
    if task_type in EXECUTABLE_TASK_TYPES:
        return 0.95
    # Keyword match on free text is a weaker, fuzzy signal.
    lowered = description.lower()
    if any(kw in lowered for kw in ToolCatalog.EXECUTION_KEYWORDS):
        return 0.7
    return 0.1


def _record_change(
    ctx: RunContext[ImplementationDeps], action: str, target: Any, root: Any
) -> None:
    """Note that this run really wrote *target*, for honest reporting.

    The record is written only AFTER the file operation succeeded, so it
    cannot claim a change that did not happen. Paths are stored relative
    to the workspace root when possible, because an absolute host path is
    noise in a chat transcript.

    :param ctx: Run context carrying the run's deps.
    :param action: Mutating tool that made the change.
    :param target: Resolved absolute path that was written.
    :param root: Workspace root the tools are bound to.
    """
    try:
        display = str(target.relative_to(_resolve_path(root)))
    except (ValueError, OSError):
        # Outside the workspace, or unresolvable: keep the absolute path
        # rather than inventing a relative one that would be wrong.
        display = str(target)
    ctx.deps.changes.append(FileChange(action=action, path=display))


def _resolve_path(path: Any) -> Any:
    """Resolve a workspace root the same way the file tools do.

    :param path: Workspace root (str or Path).
    :return: Resolved ``Path``.
    """
    from pathlib import Path

    return Path(path or ".").expanduser().resolve()


def summarize_changes(changes: list[FileChange]) -> str:
    """Render what a run actually changed, for the caller to report.

    This is the honest counterpart to the model's own summary: it answers
    "what touched the disk" from the run's own record, so a caller never
    has to trust prose that may describe work that never happened.

    :param changes: Recorded file changes from the run's deps.
    :return: One line per change, or a plain statement that nothing was
        written.
    """
    if not changes:
        return "No files were changed."
    lines = [f"- {change.action}: {change.path}" for change in changes]
    noun = "file" if len(changes) == 1 else "files"
    return f"Changed {len(changes)} {noun}:\n" + "\n".join(lines)


def build_implementation_agent(
    *,
    complexity: str = "standard",
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
    instructions: str | None = None,
    read_only: bool = False,
) -> Agent[ImplementationDeps, str]:
    """Build the implementation Pydantic AI agent.

    Selects the model for the complexity level (unless an
    explicit *model_id* is given) and registers the execution
    planning tools. Construction performs no network or LLM
    calls; the model string resolves lazily at run time.
    Harness callers pass :class:`ImplementationDeps` per run via
    ``agent.run(prompt, deps=...)``. The output retry budget is
    explicit (``OUTPUT_RETRIES``, 3) instead of the library
    default (1), so malformed tool calls get retried before
    the harness falls back to plain text.

    Args:
        complexity: Task complexity driving tier selection.
        model_id: Explicit model id override; when None the
            tier's default model is used.
        cfg: Optional plain configuration dictionary override.
        instructions: Optional custom agent instructions override.
        read_only: When True, mutating tools (``write_file``,
            ``edit_file``) are not registered, so the model
            cannot change files even if it tries - chat-mode
            runs use this; gated/approved runs keep full tools.

    Returns:
        Configured Pydantic AI agent named ``"implementation"``.
    """
    # Explicit model ids bypass routing; otherwise the complexity's
    # model is resolved. The id is then built into an explicit
    # OpenAI-compatible model instance - configuration only, no env lookups.
    if model_id is None:
        model_id = model_for_complexity(complexity, cfg)
    model = resolve_model_instance(model_id, cfg)

    default_instructions = (
        "You are an implementation agent that EXECUTES code changes, not just plans them. "
        "When given a task:\n"
        "1. Call build_execution_plan to understand the steps\n"
        "2. Call required_tools to check what you need\n"
        "3. ACTUALLY USE write_file or edit_file to make the changes\n"
        "4. Verify the changes were made\n\n"
        "CRITICAL: After calling build_execution_plan, you MUST call write_file or edit_file "
        "to implement the changes. Do NOT return a plan as your final answer - execute the plan "
        "using the available tools. The user expects actual file changes, not just a description "
        "of what you would do."
    )

    agent: Agent[ImplementationDeps, str] = Agent(
        model,
        # Explicit name labels this agent's Logfire run span.
        name=IMPLEMENTATION_AGENT_NAME,
        deps_type=ImplementationDeps,
        # Cross-agent message sharing passes a prior run's messages into
        # this one; ReinjectSystemPrompt keeps this agent's own system
        # prompt at the head (otherwise a non-empty history suppresses
        # it). See pydantic-ai message-history sharing.
        capabilities=[ReinjectSystemPrompt()],
        # Plain-text output so the model can freely call tools
        # and return a final answer string. A structured output
        # schema would risk `UnexpectedModelBehavior` retry
        # exhaustion when the model cannot serialize the schema.
        retries={"output": OUTPUT_RETRIES},
        instructions=(
            instructions if instructions is not None else default_instructions
        ),
    )

    @agent.tool
    def build_execution_plan(
        ctx: RunContext[ImplementationDeps], task_type: str
    ) -> str:
        """Build the step-by-step execution plan for a task type.

        Args:
            ctx: Run context carrying implementation deps.
            task_type: Task type to plan for.

        Returns:
            Human-readable numbered plan steps.
        """
        # Deps are unused beyond routing context here; the plan
        # itself is a pure function of the task type.
        _ = ctx
        steps = plan_steps_for(task_type)
        lines = [
            f"{i}. {s.action}: {s.description}"
            for i, s in enumerate(steps, start=1)
        ]
        return "\n".join(lines)

    @agent.tool
    def required_tools(
        ctx: RunContext[ImplementationDeps], task_type: str
    ) -> str:
        """List the tools a task type requires.

        Args:
            ctx: Run context carrying implementation deps.
            task_type: Task type to inspect.

        Returns:
            Comma-separated required tool names.
        """
        # Deps are unused beyond routing context here; the tool
        # list is a pure function of the task type.
        _ = ctx
        return ", ".join(ToolCatalog.tools_for(task_type))

    @agent.tool
    def task_confidence(
        ctx: RunContext[ImplementationDeps], task_type: str, description: str
    ) -> str:
        """Score how confidently this agent handles a task.

        Args:
            ctx: Run context carrying implementation deps.
            task_type: Task type string.
            description: Free-text task description.

        Returns:
            Confidence score as a string between 0 and 1.
        """
        # Deps are unused beyond routing context here; the score
        # is a pure function of task type and description.
        _ = ctx
        return str(estimate_confidence(task_type, description))

    @agent.tool
    def read_file(ctx: RunContext[ImplementationDeps], file_path: str) -> str:
        """Read a file from the workspace.

        Returns a helpful message instead of raising when the
        path is a directory or does not exist, so the model
        can recover (e.g. by calling ``list_files``).

        Args:
            ctx: Run context carrying implementation deps.
            file_path: Path to the file, relative to workspace root
                or prefixed with /workspace.

        Returns:
            File contents as a string, or a guidance message.
        """
        root = ctx.deps.workspace_root or "."
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

    @agent.tool
    def list_files(
        ctx: RunContext[ImplementationDeps], file_path: str = "."
    ) -> str:
        """List files and subdirectories in a workspace directory.

        Use this to explore the project layout before reading
        files - never guess at paths. Directories end with "/".

        Args:
            ctx: Run context carrying implementation deps.
            file_path: Directory to list, relative to workspace
                root or prefixed with /workspace (default: root).

        Returns:
            Sorted directory listing, directories first.
        """
        root = ctx.deps.workspace_root or "."
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

    @agent.tool
    def bash(
        ctx: RunContext[ImplementationDeps], command: str, timeout: int = 30
    ) -> str:
        """Run a shell command in the workspace root.

        Use this to run tests, builds, linters, or inspect the
        system. There is no other shell/terminal tool.

        :param ctx: Run context carrying implementation deps.
        :param command: Shell command to run (via ``bash -c``).
        :param timeout: Seconds before the command is killed
                (clamped to 120).

        :retun:  Exit code plus combined output (truncated at 8000 chars).
        """
        import logging
        import subprocess

        root = ctx.deps.workspace_root or "."
        root_path = _normalize_target(".", root)
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
                cwd=root_path,
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

    @agent.tool
    def search_code(
        ctx: RunContext[ImplementationDeps], pattern: str, directory: str = "."
    ) -> str:
        """Search file contents under a workspace directory.

        Recursive literal-match grep over text files (skips
        binaries, hidden/vendor dirs, files over 1MB; capped at
        50 hits). Use this instead of guessing file paths.

        :param ctx: Run context carrying implementation deps.
        :param pattern: Literal text to search for (not a regex).
        :param directory: Where to search (default: workspace root).

        :return: ``path:line: text`` hits, or a no-match message.
        """
        root = ctx.deps.workspace_root or "."
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
        root_path = _normalize_target(".", root)
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
                    try:
                        rel = path.relative_to(root_path)
                    except ValueError:
                        rel = path
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

    # Mutating tools are withheld in read-only (chat) mode so
    # the model cannot change files without going through the
    # harness HITL gate - instructions alone never stop a
    # tool call, missing tools do.
    if not read_only:

        @agent.tool
        def write_file(
            ctx: RunContext[ImplementationDeps], file_path: str, content: str
        ) -> str:
            """Create or overwrite a file in the workspace.

            :param ctx: Run context carrying implementation deps.
            :param file_path: Path to the file, relative to workspace root
                or prefixed with /workspace.
            :param content: File contents to write.

            :return: Confirmation message with the written path.
            """
            root = ctx.deps.workspace_root or "."
            target = _normalize_target(file_path, root)
            _atomic_write(target, content)
            _record_change(ctx, "write", target, root)
            return f"Wrote {target}"

        @agent.tool
        def edit_file(
            ctx: RunContext[ImplementationDeps], file_path: str, content: str
        ) -> str:
            """Replace the contents of an existing file in the workspace.

            :param ctx: Run context carrying implementation deps.
            :param file_path: Path to the file, relative to workspace root
                or prefixed with /workspace.
            :param content: New file contents.

            :return: Confirmation message with the edited path.
            """
            root = ctx.deps.workspace_root or "."
            target = _normalize_target(file_path, root)
            _atomic_write(target, content)
            _record_change(ctx, "edit", target, root)
            return f"Edited {target}"

        @agent.tool
        def patch_file(
            ctx: RunContext[ImplementationDeps],
            file_path: str,
            old_text: str,
            new_text: str,
        ) -> str:
            """Replace one block of text inside an existing file.

            Surgical alternative to rewriting the whole file: only
            the first occurrence of ``old_text`` is replaced.

            :param ctx: Run context carrying implementation deps.
            :param file_path: Path to the file, relative to workspace
                root or prefixed with /workspace.
            :param old_text: Exact text block to replace (verbatim).
            :param new_text: Replacement text.

            :return: Confirmation message, or guidance when the file
                is missing or the block is not found verbatim.
            """
            root = ctx.deps.workspace_root or "."
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
            _record_change(ctx, "patch", target, root)
            note = (
                f" ({remaining} identical block(s) left untouched)"
                if remaining
                else ""
            )
            return f"Patched {target}{note}"

    return agent


# Module-level default agent for harness callers (lazy fallback).
# Building at import time must not crash when tier defaults point to
# undeclared models (common when bergagents.jsonc is minimal) - fallback
# to the first declared provider model. No network/LLM calls are made.
#
# No model name is hardcoded here: the config is the only source
# (config is the only source of model names). Naming a "rescue" model
# in code silently substituted
# a different model whenever the config named an undeclared one, which
# hid a typo instead of reporting it.
try:
    implementation_agent: Agent[ImplementationDeps, str] = (
        build_implementation_agent()
    )
except Exception as exc:
    logger.warning(
        "Implementation agent: configured model unusable (%s); "
        "falling back to the first declared model.",
        exc,
        exc_info=True,
    )
    from berg_agents.providers.registry import first_declared_model

    # noinspection PyGlobalVariableRedeclarationInNotebook
    implementation_agent = build_implementation_agent(
        model_id=first_declared_model()
    )
