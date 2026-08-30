"""Learning agent for berg_agents.

Records task outcomes, updates routing rules based on success/failure,
feeds MemPalace knowledge graph, and tracks model performance per task type.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.interface import AbstractAgent, AgentResult, TaskContext
from berg_agents.core.model_router import ModelRouter

logger = logging.getLogger(__name__)


class Learning(AbstractAgent):
    """Learning agent — adaptive improvement from task outcomes.

    After tasks complete, the Learning agent:
    - Records: task type, model used, outcome
    - Identifies patterns: which models work best for which tasks
    - Updates routing rules based on evidence
    - Feeds long-term memory (MemPalace)
    """

    name: str = "learning"
    description = "Records outcomes and adapts routing decisions"
    preferred_model_tier: str = "medium"
    capabilities: list[str] = [
        "outcome_recording",
        "routing_adaptation",
        "performance_tracking",
        "pattern_learning",
    ]

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize the Learning agent.

        Args:
            router: Optional ModelRouter for accessing outcome stats.
        """
        self.router = router or ModelRouter()
        self._learnings: list[dict[str, Any]] = []

    def can_handle(self, task: dict[str, Any]) -> float:
        """Learning handles outcome recording and analysis tasks.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score based on task type.
        """
        task_type = task.get("task_type", "")

        learning_types = {
            "record_outcome",
            "analyze",
            "learn",
            "adapt",
            "review_performance",
        }

        if task_type in learning_types:
            return 1.0

        description = task.get("description", "").lower()
        learning_keywords = [
            "learn from",
            "analyze outcome",
            "record result",
            "review",
        ]
        if any(kw in description for kw in learning_keywords):
            return 0.7

        return 0.1

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Record outcome and generate learnings.

        Args:
            task: Task dictionary with outcome data.
            context: Task context.
            model: Unused for Learning agent.

        Returns:
            AgentResult with learning summary.
        """
        metadata = context.metadata
        task_type = task.get("task_type", "unknown")
        model_used = metadata.get("model_used", "unknown")
        success = metadata.get("success", True)
        user_corrected = metadata.get("user_corrected", False)

        # Record the outcome
        self.router.record_outcome(
            task,
            model=model_used,
            success=success,
            user_corrected=user_corrected,
        )

        # Generate learning entry
        learning = self._generate_learning(
            task, context, model_used, success, user_corrected
        )
        self._learnings.append(learning)

        # Get current stats
        stats = self.router.get_outcome_stats()

        return AgentResult(
            success=True,
            output={
                "status": "recorded",
                "learning": learning,
                "stats": stats,
                "recommendation": self._generate_recommendation(
                    task_type, stats
                ),
            },
            metadata={
                "total_learnings": len(self._learnings),
                "task_type": task_type,
            },
        )

    def _generate_learning(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: str,
        success: bool,
        user_corrected: bool,
    ) -> dict[str, Any]:
        """Generate a structured learning entry from an outcome.

        Args:
            task: The task that was executed.
            context: Task context.
            model: Model that was used.
            success: Whether it succeeded.
            user_corrected: Whether user had to correct.

        Returns:
            Learning entry dict.
        """
        learning: dict[str, Any] = {
            "task_type": task.get("task_type", "unknown"),
            "complexity": context.complexity.value,
            "model": model,
            "success": success,
            "user_corrected": user_corrected,
        }

        # Generate insight
        if user_corrected:
            learning["insight"] = (
                f"User correction needed for {learning['task_type']} "
                f"with {model}. Consider using a higher-tier model."
            )
            learning["action"] = "upgrade_model_tier"
        elif not success:
            learning["insight"] = (
                f"Task {learning['task_type']} failed with {model}. "
                f"Review approach or increase model capability."
            )
            learning["action"] = "review_approach"
        else:
            learning["insight"] = (
                f"{model} succeeded at {learning['task_type']} "
                f"({context.complexity.value} complexity)."
            )
            learning["action"] = "reinforce"

        return learning

    def _generate_recommendation(
        self, task_type: str, stats: dict[str, Any]
    ) -> str | None:
        """Generate a routing recommendation based on stats.

        Args:
            task_type: Type of task to check.
            stats: Outcome statistics from ModelRouter.

        Returns:
            Recommendation string or None.
        """
        by_task = stats.get("by_task_type", {})
        if task_type not in by_task:
            return None

        task_stats = by_task[task_type]
        total = task_stats["success"] + task_stats["failure"]
        if total < 3:
            return None  # Not enough data

        success_rate = task_stats["success"] / total
        if success_rate < 0.5:
            return f"Low success rate ({success_rate:.0%}) for {task_type}. Consider upgrading model tier."
        elif success_rate > 0.9 and total >= 5:
            return f"High success rate ({success_rate:.0%}) for {task_type}. May downgrade model tier to save costs."

        return None

    def get_learnings(self) -> list[dict[str, Any]]:
        """Return all recorded learnings.

        Returns:
            List of learning entries.
        """
        return list(self._learnings)

    def get_best_model_for_task(self, task_type: str) -> str | None:
        """Determine the best model for a task type based on outcomes.

        Args:
            task_type: Type of task.

        Returns:
            Best performing model name or None.
        """
        stats = self.router.get_outcome_stats()
        by_model = stats.get("by_model", {})

        best_model: str | None = None
        best_rate = -1.0

        for model, model_stats in by_model.items():
            total = model_stats["success"] + model_stats["failure"]
            if total < 2:
                continue
            rate = model_stats["success"] / total
            if rate > best_rate:
                best_rate = rate
                best_model = model

        return best_model
