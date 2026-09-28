"""Implementation Pydantic AI agent for berg_agents.

Executes code changes: builds a step-by-step execution plan for a
task type, reports which tools the task needs, and scores how
confidently this agent can handle a task.

Model selection resolves the task complexity directly onto a model
from ``config/bergagents.jsonc`` (``model_routing.models``), formatted
as a ``provider:model`` string via
:func:`berg_agents.providers.models.resolve_model_string`.

By design this module imports nothing from LangChain, LangGraph, or
DeepAgents.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "resolve_implementation_model",
]

# Explicit output retry budget for the implementation agent.
# Spec name: ``output_retries (2)``. Pydantic AI v2 exposes it
# as the ``output`` entry of ``Agent(retries=...)`` (library
# default 1 for both budgets); the dict form below sets only
# the output budget and leaves the tool budget at its default.
OUTPUT_RETRIES = 2

# Explicit agent name: labels this agent's run span in Logfire so
# traces stay distinguishable when several agents run in one app.
IMPLEMENTATION_AGENT_NAME = "implementation"

# Complexity Level type: plain strings so this module stays
# decoupled from the old core interface being removed.
ComplexityLevel = Literal["trivial", "standard", "complex", "critical"]

# Task types this agent executes with high confidence.
EXECUTABLE_TASK_TYPES: frozenset[str] = frozenset(
    {
        "edit_file",
        "new_file",
        "read_file",
        "delete_file",
        "generate_test",
        "format_code",
        "execute_command",
        "refactor",
        "implement",
        "fix",
    }
)

# Step-by-step execution plans per task type.
_PLAN_STEPS: dict[str, list[dict[str, str]]] = {
    "edit_file": [
        {"action": "read_file", "description": "Read file content"},
        {"action": "analyze", "description": "Analyze changes"},
        {"action": "apply_edit", "description": "Apply the edit"},
        {"action": "verify", "description": "Verify the change"},
    ],
    "new_file": [
        {"action": "check_exists", "description": "Check file exists"},
        {"action": "create_file", "description": "Create new file"},
        {"action": "populate", "description": "Write content"},
    ],
    "delete_file": [
        {"action": "confirm", "description": "Confirm safe deletion"},
        {"action": "backup_check", "description": "Check dependencies"},
        {"action": "delete", "description": "Delete the file"},
    ],
    "generate_test": [
        {"action": "read_source", "description": "Read source code"},
        {"action": "analyze_coverage", "description": "Find gaps"},
        {"action": "generate", "description": "Generate test cases"},
        {"action": "write_test", "description": "Write test file"},
    ],
}

# Fallback plan for task types without a dedicated template.
_GENERIC_PLAN: list[dict[str, str]] = [
    {"action": "analyze", "description": "Analyze the task"},
    {"action": "execute", "description": "Execute the operation"},
    {"action": "verify", "description": "Verify the result"},
]


@dataclass
class ImplementationDeps:
    """Dependencies injected into each implementation agent run.

    Attributes:
        workspace_root: Workspace directory file tools are bound to.
        complexity: Task complexity level driving model selection.
        task_type: Task type being executed (e.g. ``"edit_file"``).
    """

    workspace_root: str = "."
    complexity: str = "standard"
    task_type: str = "generic"


class PlanStep(BaseModel):
    """One step of an execution plan.

    Attributes:
        action: Machine-readable step identifier.
        description: Human-readable step summary.
    """

    action: str
    description: str


def resolve_implementation_model(
    complexity: str = "standard",
    cfg: dict[str, Any] | None = None,
) -> str:
    """Resolve the ``provider:model`` string for a complexity level.

    Looks up the complexity's model directly, then formats it through
    :func:`resolve_model_string` so the result always carries the
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

    Args:
        task_type: Task type (e.g. ``"edit_file"``).

    Returns:
        Ordered list of plan steps; never empty.
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

    Args:
        task_type: Task type string.
        description: Free-text task description.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    # Exact task-type match is the strongest signal.
    if task_type in EXECUTABLE_TASK_TYPES:
        return 0.95
    # Keyword match on free text is a weaker, fuzzy signal.
    lowered = description.lower()
    if any(kw in lowered for kw in ToolCatalog.EXECUTION_KEYWORDS):
        return 0.7
    return 0.1


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
    explicit (``OUTPUT_RETRIES``, 2) instead of the library
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
            cannot change files even if it tries — chat-mode
            runs use this; gated/approved runs keep full tools.

    Returns:
        Configured Pydantic AI agent named ``"implementation"``.
    """
    # Explicit model ids bypass routing; otherwise the complexity's
    # model is resolved. The id is then built into an explicit
    # OpenAI-compatible model instance — config only, no env lookups.
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
        ctx: RunContext[ImplementationDeps],
        task_type: str,
        description: str,
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
    def read_file(
        ctx: RunContext[ImplementationDeps],
        file_path: str,
    ) -> str:
        """Read a file from the workspace.

        Args:
            ctx: Run context carrying implementation deps.
            file_path: Path to the file, relative to workspace root
                or prefixed with /workspace.

        Returns:
            File contents as a string.
        """
        root = ctx.deps.workspace_root or "."
        target = _normalize_target(file_path, root)
        return target.read_text(encoding="utf-8")

    # Mutating tools are withheld in read-only (chat) mode so
    # the model cannot change files without going through the
    # harness HITL gate — instructions alone never stop a
    # tool call, missing tools do.
    if not read_only:

        @agent.tool
        def write_file(
            ctx: RunContext[ImplementationDeps],
            file_path: str,
            content: str,
        ) -> str:
            """Create or overwrite a file in the workspace.

            Args:
                ctx: Run context carrying implementation deps.
                file_path: Path to the file, relative to workspace root
                    or prefixed with /workspace.
                content: File contents to write.

            Returns:
                Confirmation message with the written path.
            """
            root = ctx.deps.workspace_root or "."
            target = _normalize_target(file_path, root)
            _atomic_write(target, content)
            return f"Wrote {target}"

        @agent.tool
        def edit_file(
            ctx: RunContext[ImplementationDeps],
            file_path: str,
            content: str,
        ) -> str:
            """Replace the contents of an existing file in the workspace.

            Args:
                ctx: Run context carrying implementation deps.
                file_path: Path to the file, relative to workspace root
                    or prefixed with /workspace.
                content: New file contents.

            Returns:
                Confirmation message with the edited path.
            """
            root = ctx.deps.workspace_root or "."
            target = _normalize_target(file_path, root)
            _atomic_write(target, content)
            return f"Edited {target}"

    return agent


# Module-level default agent for harness callers (lazy fallback).
# Building at import time must not crash when tier defaults point to
# undeclared models (common when bergagents.jsonc is minimal) — fallback
# to the first declared provider model. No network/LLM calls are made.
try:
    implementation_agent: Agent[ImplementationDeps, str] = (
        build_implementation_agent()
    )
except Exception:
    try:
        # Retry with explicit first-declared model (None = first in registry)
        implementation_agent = build_implementation_agent(model_id=None)
    except Exception:
        # Last resort: known declared model that always exists in this repo
        implementation_agent = build_implementation_agent(
            model_id="nemotron-3-nano:30b-cloud"
        )
