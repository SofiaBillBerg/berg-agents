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

"""Planner agent for berg_agents (Pydantic AI rebuild).

Breaks down high-level tasks into subtasks, estimates
complexity, determines dependencies, and suggests optimal
execution order.

The deterministic decomposition behavior (pattern-based
templates, complexity estimation, tier mapping, topological
ordering) is implemented here as pure module-level functions.
A named Pydantic AI
:class:`~pydantic_ai.Agent` exposes that behavior to the
model through tools, and the :class:`Planner` facade keeps
the ``can_handle`` / ``execute`` contract used by callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, ClassVar

from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    TaskComplexity,
    TaskContext,
)
from berg_agents.providers.models import resolve_model_instance
from berg_agents.providers.tiers import model_for_complexity
from pydantic_ai import Agent, RunContext, Tool

logger = logging.getLogger(__name__)

__all__ = [
    "Planner",
    "PlannerDeps",
    "Subtask",
    "build_plan",
    "build_planner_agent",
    "decompose",
    "estimate_complexity",
    "order_subtasks",
    "plan_depth",
    "planner_agent"]

#: Explicit Pydantic AI agent name (labels Logfire run spans).
PLANNER_NAME = "planner"

#: Preferred complexity for planning (mirrors the ``agents``
#: block of ``.berg-agents/bergagents.jsonc``).
PLANNER_COMPLEXITY = "complex"

#: Keywords mapping a task onto CRITICAL complexity.
_CRITICAL_KEYWORDS = ("delete", "security", "production")

#: Keywords mapping a task onto COMPLEX complexity.
_COMPLEX_KEYWORDS = ("refactor", "architecture", "multi_file")

#: Keywords mapping a task onto TRIVIAL complexity.
_TRIVIAL_KEYWORDS = ("read_file", "list_files", "search")

#: Task types that always request planning with full confidence.
_PLAN_TASK_TYPES = frozenset({"plan", "decompose", "breakdown"})

#: System instructions for the planner agent.
_PLANNER_INSTRUCTIONS = (
    "You break high-level coding tasks into ordered subtasks. "
    "Use the decompose_task tool for pattern-based plans and "
    "the estimate_task_complexity tool to grade complexity. "
    "Complex and critical work needs larger models and human "
    "review; trivial work stays on small models."
)


@dataclass
class Subtask:
    """A single subtask within a plan."""

    id: str
    description: str
    task_type: str
    complexity: TaskComplexity
    dependencies: list[str] = field(default_factory=list)
    estimated_complexity: str = "standard"

    def to_dict(self) -> dict[str, Any]:
        """Return the subtask as a plain dictionary.

        Used for JSON serialization in plan outputs. The
        ``estimated_complexity`` field is included for convenience
        even though it duplicates the ``complexity`` value.

        :return: Dictionary representation of the subtask.
        """
        # Values stay JSON-serializable for API responses.
        return {
            "id": self.id,
            "description": self.description,
            "task_type": self.task_type,
            "complexity": self.complexity.value,
            "dependencies": self.dependencies,
            "estimated_complexity": self.estimated_complexity}

    @classmethod
    def simple(
        cls, subtask_id: str, description: str, task_type: str = "generic"
    ) -> Subtask:
        """Create a subtask with default STANDARD complexity."""
        # Single-step fallback for tasks matching no template.
        return cls(
            id=subtask_id,
            description=description,
            task_type=task_type,
            complexity=TaskComplexity.STANDARD,
        )


@dataclass
class PlannerDeps:
    """Dependencies injected into planner tool runs."""


def estimate_complexity(
    description: str, task_type: str = "generic"
) -> TaskComplexity:
    """Estimate task complexity from keywords.

    Args:
        description: Human-readable task description.
        task_type: Machine task type (e.g. ``refactor``).

    Returns:
        The estimated :class:`TaskComplexity` level.
    """
    # Match against the combined text so either the type or
    # the wording can trigger a rule, as before.
    combined = f"{task_type} {description}".lower()
    if any(key in combined for key in _CRITICAL_KEYWORDS):
        return TaskComplexity.CRITICAL
    if any(key in combined for key in _COMPLEX_KEYWORDS):
        return TaskComplexity.COMPLEX
    if any(key in combined for key in _TRIVIAL_KEYWORDS):
        return TaskComplexity.TRIVIAL
    return TaskComplexity.STANDARD


def _decompose_refactor() -> list[Subtask]:
    """Build the analyze-plan-edit-test refactor template.

    :return: Ordered list of subtasks for refactoring work.
    """
    # Four ordered steps; later steps depend on earlier ones.
    return [
        Subtask(
            id="1",
            description=(
                "Analyze current code structure and identify areas to refactor"
            ),
            task_type="search_code",
            complexity=TaskComplexity.TRIVIAL,
        ),
        Subtask(
            id="2",
            description=(
                "Plan the refactoring approach and identify dependencies"
            ),
            task_type="plan",
            complexity=TaskComplexity.STANDARD,
            dependencies=["1"],
        ),
        Subtask(
            id="3",
            description="Execute code changes for refactoring",
            task_type="edit_file",
            complexity=TaskComplexity.COMPLEX,
            dependencies=["2"],
        )]


def _decompose_implement() -> list[Subtask]:
    """Build the design-implement-test template.

    :return: Ordered list of subtasks for new-feature work.
    """
    # Three ordered steps for new-feature work.
    return [
        Subtask(
            id="1",
            description="Analyze requirements and design approach",
            task_type="plan",
            complexity=TaskComplexity.STANDARD,
        ),
        Subtask(
            id="2",
            description="Create new files and implement core logic",
            task_type="new_file",
            complexity=TaskComplexity.COMPLEX,
            dependencies=["1"],
        )]


def _decompose_fix() -> list[Subtask]:
    """Build the diagnose-fix-regression-test template.

    :return: Ordered list of subtasks for bug-fix work.
    """
    # Three ordered steps for bug-fix work.
    return [
        Subtask(
            id="1",
            description="Identify the root cause of the bug",
            task_type="search_code",
            complexity=TaskComplexity.STANDARD,
        ),
        Subtask(
            id="2",
            description="Implement the fix",
            task_type="edit_file",
            complexity=TaskComplexity.STANDARD,
            dependencies=["1"],
        )]


def decompose(description: str, task_type: str = "generic") -> list[Subtask]:
    """Decompose a task into subtasks via pattern templates.

    Uses keyword matching for common task types; anything
    else becomes a single generic subtask.

    :param description: Human-readable task description.
    :param task_type: Machine task type.

    :return:: Unordered list of subtasks (order with
        :func:`order_subtasks`).
    """
    # Lowercase once so every branch shares one normalized copy.
    lowered = description.lower()
    if "refactor" in lowered:
        return _decompose_refactor()
    if "implement" in lowered or "create" in lowered:
        return _decompose_implement()
    if "fix" in lowered or "bug" in lowered:
        return _decompose_fix()
    return [Subtask.simple("1", description, task_type)]


def order_subtasks(subtasks: list[Subtask]) -> list[Subtask]:
    """Sort subtasks in dependency order (topological sort).

    Tasks with no dependencies come first.

    :param subtasks: Subtasks in any order.

    :return: Subtasks ordered so dependencies precede dependents.
    """
    # Map ids for O(1) lookup during the depth-first walk.
    subtask_map = {s.id: s for s in subtasks}
    visited: set[str] = set()
    result: list[Subtask] = []

    def visit(subtask_id: str) -> None:
        """Append one subtask after its dependencies.

        :param subtask_id: Subtask id to visit.
        """
        # Skip repeats and dangling dependency ids silently.
        if subtask_id in visited:
            return
        visited.add(subtask_id)
        subtask = subtask_map.get(subtask_id)
        if subtask is not None:
            for dep in subtask.dependencies:
                visit(dep)
            result.append(subtask)

    for subtask in subtasks:
        visit(subtask.id)
    return result


def plan_depth(ordered: list[Subtask]) -> int:
    """Calculate the maximum dependency depth of a plan.


    :param ordered: Topologically ordered subtasks.

    :return: Longest dependency chain length (0 when empty).
    """
    if not ordered:
        return 0
    # Memoize per-id depths; the recursion follows the DAG.
    depth_map: dict[str, int] = {}
    subtask_map = {s.id: s for s in ordered}

    def get_depth(subtask_id: str) -> int:
        """Return cached depth of one subtask.

        :param subtask_id: Subtask id to check.
        :return: Depth of the subtask (0 for no dependencies).
        """
        if subtask_id in depth_map:
            return depth_map[subtask_id]
        subtask = subtask_map.get(subtask_id)
        if subtask is None or not subtask.dependencies:
            depth_map[subtask_id] = 0
            return 0
        chained = max(get_depth(d) for d in subtask.dependencies)
        depth_map[subtask_id] = chained + 1
        return depth_map[subtask_id]

    return max(get_depth(s.id) for s in ordered)


def suggest_planning_hint(
    plan: dict[str, Any], complexity: TaskComplexity
) -> dict[str, Any] | None:
    """Suggest harness Planning capability when multi-step planning is needed."""
    if complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
        return {
            "capability": "Planning",
            "enable_subtasks": True,
            "reason": "complex/critical"}
    multi_step_threshold = 2
    if plan.get("total_subtasks", 0) > multi_step_threshold:
        return {
            "capability": "Planning",
            "enable_subtasks": True,
            "reason": f"multi-step ({plan.get('total_subtasks')})"}
    return None


def build_plan(
    description: str,
    task_type: str = "generic",
    complexity: TaskComplexity = TaskComplexity.STANDARD,
) -> dict[str, Any]:
    """Build a full ordered plan dictionary for a task.

    Decomposes, re-estimates each subtask, assigns model
    tiers, and sorts into execution order.

    Args:
        description: Human-readable task description.
        task_type: Machine task type.
        complexity: Overall task complexity for the header.

    Returns:
        Plan mapping with ``subtasks``, ``total_subtasks``,
        ``estimated_complexity``, and ``plan_depth``.
    """
    subtasks = decompose(description, task_type)
    for subtask in subtasks:
        # Re-grade every template step from its own text so
        # complexity tracks the subtask, not the parent task.
        subtask.complexity = estimate_complexity(
            subtask.description, subtask.task_type
        )
        subtask.estimated_complexity = subtask.complexity.value
    ordered = order_subtasks(subtasks)
    return {
        "subtasks": [s.to_dict() for s in ordered],
        "total_subtasks": len(ordered),
        "estimated_complexity": complexity.value,
        "plan_depth": plan_depth(ordered)}


def build_planner_agent(
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
    *,
    plugin_tools: list[Tool[PlannerDeps]] | None = None,
) -> Agent[PlannerDeps, str]:
    """Build the planner Pydantic AI agent.

    The model is always an explicit OpenAI-compatible instance
    from :func:`berg_agents.providers.models.resolve_model_instance`;
    bare model ids are rejected there, never here.

    :param model_id: Model id override; the complexity default when None.
    :param cfg: Plain configuration override.
    :param plugin_tools: Tools the ``planner`` role may use, already
        resolved and session-bound by the caller via
        :func:`plugin_system.get_plugin_tools_for`. The planner is what
        *writes* the plan into a plugin store (shared-todo), so these
        must be the same session-bound tools the chat agent and the
        implementer read.
    :return: Configured planner agent.
    """
    # Fall back to the planner complexity model so explicit ids
    # stay optional while the complexity preference is kept.
    if model_id is None:
        model_id = model_for_complexity(PLANNER_COMPLEXITY, cfg)
    # Specialized on the constructor for the same reason as the
    # implementation agent: an unparameterized call infers `object` for
    # the deps slot and contradicts the declared return type.
    agent: Agent[PlannerDeps, str] = Agent[PlannerDeps, str](
        resolve_model_instance(model_id, cfg),
        name=PLANNER_NAME,
        deps_type=PlannerDeps,
        instructions=_PLANNER_INSTRUCTIONS,
        # Empty by default, so the module-level instance below still
        # builds without a plugin system; role callers pass the bound
        # plan tools in.
        tools=list(plugin_tools or []),
    )
    return agent


#: Module-level planner agent for the harness to import.
#: Construction resolves the model string only; no network
#: or LLM call happens until the agent is run.
#:
#: No model name is hardcoded here: the config is the only source
#: (config is the only source of model names). When resolution fails
#: the tier default is dropped
#: in favor of the first model the registry declares (``None``), and
#: the failure is logged loudly so a typo in ``model_routing`` is
#: visible instead of silently substituting some other model.
#:
#: The annotation carries the deps type, like the builder's return type:
#: a bare ``Agent`` here would erase it and report the assignment of a
#: correctly-typed agent as an error.
try:
    planner_agent: Agent[PlannerDeps, str] = build_planner_agent()
except Exception as exc:
    logger.warning(
        "Planner agent: configured model unusable (%s); "
        "falling back to the first declared model.",
        exc,
        exc_info=True,
    )
    from berg_agents.providers.registry import first_declared_model

    planner_agent = build_planner_agent(first_declared_model())


@planner_agent.tool
def decompose_task(
    ctx: RunContext[PlannerDeps], description: str, task_type: str = "generic"
) -> str:
    """Decompose a task into an ordered JSON plan.

    Args:
        ctx: Run context with planner dependencies.
        description: Human-readable task description.
        task_type: Machine task type.

    Returns:
        JSON-encoded plan with subtasks in order.
    """
    # Context is unused beyond the required first param;
    # the plan itself is fully deterministic.
    _ = ctx
    return json.dumps(build_plan(description, task_type))


@planner_agent.tool
def estimate_task_complexity(
    ctx: RunContext[PlannerDeps], description: str, task_type: str = "generic"
) -> str:
    """Grade a task's complexity level.

    Args:
        ctx: Run context with planner dependencies.
        description: Human-readable task description.
        task_type: Machine task type.

    Returns:
        Complexity value (trivial/standard/complex/critical).
    """
    # Context is unused beyond the required first param;
    # grading is a pure keyword rule.
    _ = ctx
    return estimate_complexity(description, task_type).value


class Planner(AbstractAgent):
    """Planner agent - breaks down tasks into subtasks.

    Deterministic facade over :func:`build_plan` keeping the
    ``can_handle`` / ``execute`` contract. LLM-driven runs
    go through :data:`planner_agent` instead.
    """

    name: str = "planner"
    description: str = (
        "Breaks down tasks into subtasks with complexity estimates"
    )
    preferred_complexity: str = PLANNER_COMPLEXITY
    capabilities: ClassVar[list[str]] = [
        "task_decomposition",
        "complexity_estimation",
        "dependency_analysis"]

    # Instance method required by the AbstractAgent contract;
    # scoring is a pure function of the task dict.
    # ruff: ignore[no-self-use]
    def can_handle(self, task: dict[str, Any]) -> float:
        """Score confidence for handling a task.

        Full confidence for planning requests, high for
        complex/critical work, low for trivial work that
        needs no planning.

        :param task: Task dictionary.

        :return: Confidence score between 0.0 and 1.0.
        """
        task_type = task.get("task_type", "")
        if task_type in _PLAN_TASK_TYPES:
            return 1.0
        complexity = estimate_complexity(task.get("description", ""), task_type)
        if complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
            return 0.8
        if complexity == TaskComplexity.TRIVIAL:
            return 0.2
        return 0.5

    # Instance method required by the AbstractAgent contract.
    # ruff: ignore[no-self-use]
    def execute(
        self, task: dict[str, Any], context: TaskContext, model: Any = None
    ) -> AgentResult:
        """Break down the task into ordered subtasks.

        Args:
            task: Task dictionary with description.
            context: Task context with overall complexity.
            model: Unused; LLM runs use the agent instead.

        Returns:
            AgentResult with the plan in output.
        """
        # Model param kept for the AbstractAgent contract;
        # deterministic planning needs no model instance.
        _ = model
        plan = build_plan(
            task.get("description", ""),
            task.get("task_type", "generic"),
            context.complexity,
        )
        return AgentResult(
            success=True,
            output={
                "subtasks": plan["subtasks"],
                "total_subtasks": plan["total_subtasks"],
                "estimated_complexity": plan["estimated_complexity"]},
            metadata={"plan_depth": plan["plan_depth"]},
        )
