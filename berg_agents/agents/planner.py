"""Planner agent for berg_agents.

Breaks down high-level tasks into subtasks, estimates complexity,
determines dependencies, and suggests optimal execution order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    TaskComplexity,
    TaskContext,
)
from berg_agents.core.model_router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class Subtask:
    """A single subtask within a plan."""

    id: str
    description: str
    task_type: str
    complexity: TaskComplexity
    dependencies: list[str] = field(default_factory=list)
    estimated_model_tier: str = "small"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "task_type": self.task_type,
            "complexity": self.complexity.value,
            "dependencies": self.dependencies,
            "estimated_model_tier": self.estimated_model_tier,
        }

    @classmethod
    def simple(
        cls, id: str, description: str, task_type: str = "generic"
    ) -> Subtask:
        """Create a subtask with default STANDARD complexity."""
        return cls(
            id=id,
            description=description,
            task_type=task_type,
            complexity=TaskComplexity.STANDARD,
        )


class Planner(AbstractAgent):
    """Planner agent — breaks down tasks into executable subtasks.

    The Planner analyzes a high-level task and produces an ordered
    list of subtasks with complexity estimates and dependencies.
    """

    name: str = "planner"
    description: str = (
        "Breaks down tasks into subtasks with complexity estimates"
    )
    preferred_model_tier: str = "medium"
    capabilities: list[str] = [
        "task_decomposition",
        "complexity_estimation",
        "dependency_analysis",
    ]

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize the Planner.

        Args:
            router: Optional ModelRouter instance for complexity estimation.
        """
        self.router = router or ModelRouter()

    def can_handle(self, task: dict[str, Any]) -> float:
        """Planner handles decomposition requests and complex multi-step tasks.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score based on task type.
        """
        task_type = task.get("task_type", "")
        description = task.get("description", "").lower()

        # High confidence for planning requests
        if task_type in ("plan", "decompose", "breakdown"):
            return 1.0

        # Medium confidence for complex tasks
        if self.router.estimate_complexity(task) in (
            TaskComplexity.COMPLEX,
            TaskComplexity.CRITICAL,
        ):
            return 0.8

        # Lower confidence for simple tasks that don't need planning
        if self.router.estimate_complexity(task) == TaskComplexity.TRIVIAL:
            return 0.2

        return 0.5

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Break down the task into subtasks.

        Args:
            task: Task dictionary with description and optional subtasks hint.
            context: Task context.
            model: Optional LLM for advanced decomposition.

        Returns:
            AgentResult with plan (list of subtasks) in output.
        """
        description = task.get("description", "")
        task_type = task.get("task_type", "generic")

        # Decompose the task
        subtasks = self._decompose(description, task_type)

        # Estimate complexity and assign model tiers
        for subtask in subtasks:
            complexity = self.router.estimate_complexity({
                "description": subtask.description,
                "task_type": subtask.task_type,
            })
            subtask.complexity = complexity
            model_config = self.router.select_model(complexity)
            subtask.estimated_model_tier = model_config["tier"]

        # Topological sort for execution order
        ordered = self._topological_sort(subtasks)

        return AgentResult(
            success=True,
            output={
                "subtasks": [s.to_dict() for s in ordered],
                "total_subtasks": len(ordered),
                "estimated_complexity": context.complexity.value,
            },
            metadata={"plan_depth": self._max_depth(ordered)},
        )

    def _decompose(self, description: str, task_type: str) -> list[Subtask]:
        """Decompose a task into subtasks.

        Uses pattern matching for common task types.
        For more complex decomposition, an LLM can be used.
        """
        subtasks: list[Subtask] = []

        # Pattern-based decomposition
        if "refactor" in description.lower():
            subtasks = self._decompose_refactor(description)
        elif (
            "implement" in description.lower()
            or "create" in description.lower()
        ):
            subtasks = self._decompose_implement(description)
        elif "fix" in description.lower() or "bug" in description.lower():
            subtasks = self._decompose_fix(description)
        elif "test" in description.lower():
            subtasks = self._decompose_test(description)
        else:
            # Generic: create a single subtask
            subtasks = [
                Subtask(
                    id="1",
                    description=description,
                    task_type=task_type,
                    complexity=TaskComplexity.STANDARD,
                )
            ]

        return subtasks

    def _decompose_refactor(self, description: str) -> list[Subtask]:
        """Break down a refactor task."""
        return [
            Subtask(
                id="1",
                description="Analyze current code structure and identify areas to refactor",
                task_type="search_code",
                complexity=TaskComplexity.TRIVIAL,
            ),
            Subtask(
                id="2",
                description="Plan the refactoring approach and identify dependencies",
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
            ),
            Subtask(
                id="4",
                description="Run tests to verify refactoring correctness",
                task_type="generate_test",
                complexity=TaskComplexity.STANDARD,
                dependencies=["3"],
            ),
        ]

    def _decompose_implement(self, description: str) -> list[Subtask]:
        """Break down an implementation task."""
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
            ),
            Subtask(
                id="3",
                description="Add tests for new functionality",
                task_type="generate_test",
                complexity=TaskComplexity.STANDARD,
                dependencies=["2"],
            ),
        ]

    def _decompose_fix(self, description: str) -> list[Subtask]:
        """Break down a bug fix task."""
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
            ),
            Subtask(
                id="3",
                description="Add regression test",
                task_type="generate_test",
                complexity=TaskComplexity.STANDARD,
                dependencies=["2"],
            ),
        ]

    def _decompose_test(self, description: str) -> list[Subtask]:
        """Break down a test generation task."""
        return [
            Subtask(
                id="1",
                description="Identify code paths to test",
                task_type="read_file",
                complexity=TaskComplexity.TRIVIAL,
            ),
            Subtask(
                id="2",
                description="Generate test cases",
                task_type="generate_test",
                complexity=TaskComplexity.STANDARD,
                dependencies=["1"],
            ),
        ]

    def _topological_sort(self, subtasks: list[Subtask]) -> list[Subtask]:
        """Sort subtasks in dependency order (topological sort).

        Tasks with no dependencies come first.
        """
        subtask_map = {s.id: s for s in subtasks}
        visited: set[str] = set()
        result: list[Subtask] = []

        def visit(subtask_id: str) -> None:
            if subtask_id in visited:
                return
            visited.add(subtask_id)
            subtask = subtask_map.get(subtask_id)
            if subtask:
                for dep in subtask.dependencies:
                    visit(dep)
                result.append(subtask)

        for subtask in subtasks:
            visit(subtask.id)

        return result

    def _max_depth(self, ordered: list[Subtask]) -> int:
        """Calculate the maximum dependency depth of the plan."""
        if not ordered:
            return 0

        depth_map: dict[str, int] = {}
        subtask_map = {s.id: s for s in ordered}

        def get_depth(subtask_id: str) -> int:
            if subtask_id in depth_map:
                return depth_map[subtask_id]
            subtask = subtask_map.get(subtask_id)
            if not subtask or not subtask.dependencies:
                depth_map[subtask_id] = 0
                return 0
            max_dep = max(get_depth(d) for d in subtask.dependencies)
            depth_map[subtask_id] = max_dep + 1
            return depth_map[subtask_id]

        return max(get_depth(s.id) for s in ordered)
