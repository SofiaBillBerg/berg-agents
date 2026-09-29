"""Outcome-learning behavior for berg_agents.

Records task outcomes, aggregates per-model and per-task-type success
stats, and derives complexity recommendations from evidence.

The learning behavior is defined here, in this module:

- ``record_outcome`` stores task type, model, success flag.
- ``get_outcome_stats`` aggregates ``total`` /
  ``by_task_type`` / ``by_model`` success-failure counters.
- Insight actions: ``upgrade_complexity`` after a user
  correction, ``review_approach`` on failure, ``reinforce``
  on success.
- Recommendations need at least 3 samples: complexity upgrade
  below a 50 % success rate, complexity downgrade above 90 %
  with at least 5 samples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from berg_agents.core.outcome_db import ensure, insert, load

# Module logger for diagnostics.
logger = logging.getLogger(__name__)

# Minimum evidence thresholds before stats drive advice.
MIN_SAMPLES_FOR_RECOMMENDATION = 3
MIN_SAMPLES_FOR_DOWNGRADE = 5

# Success-rate boundaries for complexity-change recommendations.
UPGRADE_RATE_BELOW = 0.5
DOWNGRADE_RATE_ABOVE = 0.9

__all__ = [
    "MIN_SAMPLES_FOR_DOWNGRADE",
    "MIN_SAMPLES_FOR_RECOMMENDATION",
    "DOWNGRADE_RATE_ABOVE",
    "UPGRADE_RATE_BELOW",
    "OutcomeStore",
    "build_learning_entry",
    "get_outcome_stats",
    "recommendation_from_stats",
    "record_outcome",
]


@dataclass
class OutcomeStore:
    """Outcome store with SQLite restart survival.

    Stats shape (``total`` / ``by_task_type`` / ``by_model``) stays
    evidence-based for routing advice. Rows persist to the shared
    learning database (see :mod:`berg_agents.core.outcome_db`) so
    a restart reloads history instead of starting from zero.

    Attributes:
        outcomes: Raw recorded outcome dicts in arrival order.
        learnings: Structured learning entries in arrival order.
    """

    outcomes: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[dict[str, Any]] = field(default_factory=list)

    def __init__(
        self,
        outcomes: list[dict[str, Any]] | None = None,
        learnings: list[dict[str, Any]] | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize the store, reloading persisted rows when available."""
        self._db_path = ensure(db_path)
        self.outcomes = (
            list(outcomes)
            if outcomes is not None
            else load(self._db_path, "outcomes")
        )
        self.learnings = (
            list(learnings)
            if learnings is not None
            else load(self._db_path, "learnings")
        )

    def record_outcome(
        self,
        task_type: str,
        model: str,
        success: bool,
        user_corrected: bool = False,
        complexity: str = "standard",
    ) -> dict[str, Any]:
        """Record an outcome and return the learning summary.

        Args:
            task_type: Task-type label for aggregation.
            model: Model identifier that was used.
            success: Whether the task succeeded.
            user_corrected: Whether the user had to correct it.
            complexity: Complexity label stored on the entry.

        Returns:
            Summary dict with ``status``, ``learning``,
            ``stats``, and ``recommendation`` keys.
        """
        # Append the raw outcome before deriving stats so the
        # new sample is included in this call's snapshot.
        outcome = {
            "task_type": task_type,
            "model": model,
            "success": success,
            "user_corrected": user_corrected,
        }
        self.outcomes.append(outcome)
        # Build the structured entry from the same evidence.
        entry = build_learning_entry(
            task_type=task_type,
            complexity=complexity,
            model=model,
            success=success,
            user_corrected=user_corrected,
        )
        self.learnings.append(entry)
        # Persist both rows so a restart reloads this evidence.
        try:
            insert(self._db_path, "outcomes", outcome)
            insert(self._db_path, "learnings", entry)
        except Exception:
            logger.debug("OutcomeStore persist failed.", exc_info=True)
        logger.debug("Recorded outcome: %s/%s", task_type, model)
        # Snapshot stats after recording for the caller.
        stats = self.get_outcome_stats()
        return {
            "status": "recorded",
            "learning": entry,
            "stats": stats,
            "recommendation": recommendation_from_stats(task_type, stats),
        }

    def get_outcome_stats(self) -> dict[str, Any]:
        """Aggregate success-failure counters per scope.

        Returns:
            Dict with ``total``, ``by_task_type``, and
            ``by_model`` counters, each leaf holding
            ``success`` / ``failure`` counts.
        """
        # Fresh buckets per call so snapshots never alias.
        by_task: dict[str, dict[str, int]] = {}
        by_model: dict[str, dict[str, int]] = {}
        for outcome in self.outcomes:
            # Count once under the task-type scope.
            task_bucket = by_task.setdefault(
                str(outcome.get("task_type", "unknown")),
                {"success": 0, "failure": 0},
            )
            # Count once under the model scope.
            model_bucket = by_model.setdefault(
                str(outcome.get("model", "unknown")),
                {"success": 0, "failure": 0},
            )
            # Success and failure are exclusive tallies.
            if outcome.get("success", False):
                task_bucket["success"] += 1
                model_bucket["success"] += 1
            else:
                task_bucket["failure"] += 1
                model_bucket["failure"] += 1
        return {
            "total": len(self.outcomes),
            "by_task_type": by_task,
            "by_model": by_model,
        }


def build_learning_entry(
    task_type: str,
    complexity: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
) -> dict[str, Any]:
    """Build a structured learning entry from an outcome.

    Pure function so insight generation stays testable
    without running the agent.

    Args:
        task_type: Task-type label for the entry.
        complexity: Complexity label for the entry.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.

    Returns:
        Learning-entry dict with insight and action.
    """
    # Start from the raw evidence; insight follows below.
    entry: dict[str, Any] = {
        "task_type": task_type,
        "complexity": complexity,
        "model": model,
        "success": success,
        "user_corrected": user_corrected,
    }
    # A user correction outweighs the success flag: the
    # complexity was too low even when the task "succeeded".
    if user_corrected:
        entry["insight"] = (
            f"User correction needed for {task_type} "
            f"with {model}. Consider using a higher-complexity model."
        )
        entry["action"] = "upgrade_complexity"
        entry["type"] = "user_correction"
    elif not success:
        entry["insight"] = (
            f"Task {task_type} failed with {model}. "
            f"Review approach or increase model capability."
        )
        entry["action"] = "review_approach"
        entry["type"] = "failure"
    else:
        entry["insight"] = (
            f"{model} succeeded at {task_type} ({complexity} complexity)."
        )
        entry["action"] = "reinforce"
        entry["type"] = "success"
    return entry


def recommendation_from_stats(
    task_type: str, stats: dict[str, Any]
) -> str | None:
    """Derive a complexity-change recommendation from stats.

    Pure function so thresholds stay testable without
    running the agent.

    Args:
        task_type: Task type to evaluate.
        stats: Outcome-stats dict from ``get_outcome_stats``.

    Returns:
        Recommendation string, or None when evidence is
        thin or the success rate needs no change.
    """
    # Unknown task types carry no evidence to act on.
    by_task = stats.get("by_task_type", {})
    if task_type not in by_task:
        return None
    task_stats = by_task[task_type]
    total = task_stats["success"] + task_stats["failure"]
    # Too few samples to trust the rate either way.
    if total < MIN_SAMPLES_FOR_RECOMMENDATION:
        return None
    success_rate = task_stats["success"] / total
    # Sustained failure means the complexity is likely too low.
    if success_rate < UPGRADE_RATE_BELOW:
        return (
            f"Low success rate ({success_rate:.0%}) for "
            f"{task_type}. Consider upgrading complexity."
        )
    # Sustained success with depth may allow saving cost.
    if (
        success_rate > DOWNGRADE_RATE_ABOVE
        and total >= MIN_SAMPLES_FOR_DOWNGRADE
    ):
        return (
            f"High success rate ({success_rate:.0%}) for "
            f"{task_type}. May downgrade complexity to "
            f"save costs."
        )
    return None


# Default store backing the module-level sync helpers below.
_default_store = OutcomeStore()


def record_outcome(
    task_type: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
    complexity: str = "standard",
) -> dict[str, Any]:
    """Record an outcome in the default store.

    Sync helper for the harness learning gate, which runs
    without invoking the LLM.

    Args:
        task_type: Task-type label for aggregation.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.
        complexity: Complexity label stored on the entry.

    Returns:
        Summary dict with ``status``, ``learning``,
        ``stats``, and ``recommendation`` keys.
    """
    return _default_store.record_outcome(
        task_type=task_type,
        model=model,
        success=success,
        user_corrected=user_corrected,
        complexity=complexity,
    )


def get_outcome_stats() -> dict[str, Any]:
    """Return aggregated stats from the default store.

    Returns:
        Stats dict with ``total``, ``by_task_type``,
        and ``by_model`` counters.
    """
    return _default_store.get_outcome_stats()
