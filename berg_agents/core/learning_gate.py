"""Learning Gate for berg_agents.

The Learning Gate is the central adaptive intelligence of BergAgents.
It records outcomes from all agents, learns patterns, and feeds
long-term memory via MemPalace.

Key responsibilities:
1. Record: task type, model, outcome, user feedback
2. Learn: identify patterns in what works
3. Adapt: update routing rules based on evidence
4. Remember: store learnings in MemPalace knowledge graph
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.model_router import ModelRouter

logger = logging.getLogger(__name__)


class LearningGate:
    """Central learning system that adapts BergAgents over time.

    The Learning Gate observes all task outcomes and:
    - Tracks which models work best for which tasks
    - Identifies patterns in success/failure
    - Updates routing rules to improve future decisions
    - Stores long-term learnings in MemPalace knowledge graph
    """

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize the Learning Gate.

        Args:
            router: Optional ModelRouter for accessing outcome stats.
        """
        self.router = router or ModelRouter()
        self._insights: list[dict[str, Any]] = []
        self._rule_adjustments: list[dict[str, Any]] = []

    def record(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        success: bool,
        user_corrected: bool = False,
    ) -> dict[str, Any]:
        """Record a task outcome and generate insights.

        Args:
            task: The task that was executed.
            result: Execution result dict.
            model_used: Model identifier that was used.
            success: Whether the task succeeded.
            user_corrected: Whether the user had to correct the agent.

        Returns:
            Insight dict with learning and recommendations.
        """
        # Record in ModelRouter
        self.router.record_outcome(
            task,
            model=model_used,
            success=success,
            user_corrected=user_corrected,
        )

        # Generate insight
        insight = self._create_insight(
            task, model_used, success, user_corrected
        )
        self._insights.append(insight)

        # Check if routing rules should be adjusted
        adjustment = self._evaluate_rules(task, model_used, success)
        if adjustment:
            self._rule_adjustments.append(adjustment)
            self._apply_adjustment(adjustment)

        # Store in MemPalace
        self._store_in_mempalace(insight)

        return insight

    def _create_insight(
        self,
        task: dict[str, Any],
        model: str,
        success: bool,
        user_corrected: bool,
    ) -> dict[str, Any]:
        """Create a structured insight from an outcome.

        Args:
            task: The task that was executed.
            model: Model used.
            success: Whether it succeeded.
            user_corrected: Whether user corrected.

        Returns:
            Insight dict.
        """
        task_type = task.get("task_type", "unknown")
        complexity = task.get("complexity", "standard")

        if user_corrected:
            insight = {
                "type": "user_correction",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "upgrade_tier",
                "message": f"User correction for {task_type} with {model}. Consider higher tier.",
            }
        elif not success:
            insight = {
                "type": "failure",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "review",
                "message": f"{task_type} failed with {model}. Review approach.",
            }
        else:
            insight = {
                "type": "success",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "reinforce",
                "message": f"{model} succeeded at {task_type} ({complexity}).",
            }

        return insight

    def _evaluate_rules(
        self, task: dict[str, Any], model: str, success: bool
    ) -> dict[str, Any] | None:
        """Evaluate if routing rules should be adjusted.

        Args:
            task: The task that was executed.
            model: Model used.
            success: Whether it succeeded.

        Returns:
            Adjustment dict if rules should change, None otherwise.
        """
        stats = self.router.get_outcome_stats()
        task_type = task.get("task_type", "unknown")

        by_task = stats.get("by_task_type", {})
        if task_type not in by_task:
            return None

        task_stats = by_task[task_type]
        total = task_stats["success"] + task_stats["failure"]
        if total < 5:
            return None  # Not enough data

        success_rate = task_stats["success"] / total

        if success_rate < 0.4:
            return {
                "rule": "complexity_upgrade",
                "task_type": task_type,
                "current_rate": success_rate,
                "action": f"Upgrade model tier for {task_type} tasks (success rate: {success_rate:.0%})",
            }
        elif success_rate > 0.95 and total >= 10:
            return {
                "rule": "complexity_downgrade",
                "task_type": task_type,
                "current_rate": success_rate,
                "action": f"Consider downgrading tier for {task_type} (success rate: {success_rate:.0%})",
            }

        return None

    def _apply_adjustment(self, adjustment: dict[str, Any]) -> None:
        """Apply a routing rule adjustment.

        Args:
            adjustment: The adjustment to apply.
        """
        logger.info("Learning Gate adjustment: %s", adjustment["action"])
        # Future: update ModelRouter complexity_rules dynamically

    def _store_in_mempalace(self, insight: dict[str, Any]) -> None:
        """Store an insight in MemPalace knowledge graph.

        Args:
            insight: The insight to store.
        """
        try:
            # Use MemPalace MCP tools if available
            from berg_agents.utils.mempalace_client import store_learning

            store_learning(insight)
        except ImportError:
            # MemPalace not available, log locally
            logger.debug(
                "MemPalace not available, insight stored locally: %s", insight
            )

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive learning statistics.

        Returns:
            Dict with all learning stats.
        """
        router_stats = self.router.get_outcome_stats()
        return {
            **router_stats,
            "total_insights": len(self._insights),
            "rule_adjustments": len(self._rule_adjustments),
            "recent_insights": self._insights[-10:],
            "recent_adjustments": self._rule_adjustments[-5:],
        }

    def get_best_model(self, task_type: str) -> str | None:
        """Get the best model for a task type based on learning.

        Args:
            task_type: Type of task.

        Returns:
            Best model name or None.
        """
        return self.router.get_outcome_stats().get("by_model", {}) and next(
            (
                model
                for model, data in sorted(
                    self.router.get_outcome_stats().get("by_model", {}).items(),
                    key=lambda x: (
                        x[1].get("success", 0)
                        / max(
                            x[1].get("success", 0) + x[1].get("failure", 1), 1
                        )
                    ),
                    reverse=True,
                )
                if data.get("success", 0) + data.get("failure", 0) >= 2
            ),
            None,
        )

    def get_recommendation(self, task_type: str) -> str | None:
        """Get a routing recommendation for a task type.

        Args:
            task_type: Type of task.

        Returns:
            Recommendation string or None.
        """
        stats = self.router.get_outcome_stats()
        by_task = stats.get("by_task_type", {})

        if task_type not in by_task:
            return None

        task_stats = by_task[task_type]
        total = task_stats["success"] + task_stats["failure"]
        if total < 3:
            return None

        success_rate = task_stats["success"] / total
        if success_rate < 0.5:
            return f"Low success ({success_rate:.0%}) — use higher-tier model"
        elif success_rate > 0.9 and total >= 5:
            return (
                f"High success ({success_rate:.0%}) — can use lower-tier model"
            )

        return None


# ---------------------------------------------------------------------------
# MemPalace integration helper
# ---------------------------------------------------------------------------


class MemPalaceStore:
    """Helper to store learnings in MemPalace knowledge graph.

    This provides a bridge between the Learning Gate and MemPalace
    for long-term memory storage.
    """

    @staticmethod
    def store(insight: dict[str, Any]) -> bool:
        """Store an insight in MemPalace.

        Args:
            insight: The insight to store.

        Returns:
            True if stored successfully.
        """
        try:
            # Try to use MemPalace MCP tools
            import tools  # MCP tools available in runtime

            tools.memory.add_observations(
                observations=[
                    {
                        "entityName": f"learning_{insight.get('task_type', 'unknown')}",
                        "contents": [
                            insight.get("message", ""),
                            f"model: {insight.get('model', 'unknown')}",
                            f"action: {insight.get('action', 'none')}",
                        ],
                    }
                ]
            )
            return True
        except (ImportError, AttributeError):
            return False

    @staticmethod
    def recall(task_type: str) -> list[str]:
        """Recall learnings for a task type from MemPalace.

        Args:
            task_type: Type of task.

        Returns:
            List of observations.
        """
        try:
            import tools

            graph = tools.memory.read_graph()
            observations = []
            for entity in graph.get("entities", []):
                if entity.get("name") == f"learning_{task_type}":
                    observations.extend(entity.get("observations", []))
            return observations
        except (ImportError, AttributeError):
            return []
