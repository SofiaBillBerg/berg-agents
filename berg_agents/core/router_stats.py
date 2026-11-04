# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
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

"""Router Stats — the Router Dashboard for berg_agents.

Single module, single path: every outcome recorded by any execution
surface (chat, ``execute_task``, the tool endpoint) lands here, is
aggregated into stats, and is persisted through
:mod:`berg_agents.core.outcome_db` so a restart reloads history
instead of starting from zero.

Contents:

- :class:`OutcomeStore` — the store: outcome rows + aggregation.
- :func:`build_router_stats_entry` — **the one** entry builder.
- :func:`recommendation_from_stats` — complexity advice from evidence.
- :class:`RouterStats` — the harness-facing facade the app holds.

This is NOT a learning system. Learning is WHAT/WHY and lives in
Shared Context (see ADR-0001). MemPalace/Hindsight are optional
plugins and are never written to from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from berg_agents.core.outcome_db import ensure, insert, load

logger = logging.getLogger(__name__)

# Minimum outcomes before routing rules may be adjusted.
MIN_OUTCOMES_FOR_ADJUSTMENT = 5

# Success rate below which a complexity upgrade is suggested.
LOW_SUCCESS_RATE = 0.4

# Success rate above which a complexity downgrade is considered.
HIGH_SUCCESS_RATE = 0.95

# Minimum outcomes before a complexity downgrade is considered.
MIN_OUTCOMES_FOR_DOWNGRADE = 10

# Minimum evidence before stats drive advice.
MIN_SAMPLES_FOR_RECOMMENDATION = 3
MIN_SAMPLES_FOR_DOWNGRADE = 5

# Success-rate boundaries for complexity-change recommendations.
UPGRADE_RATE_BELOW = 0.5
DOWNGRADE_RATE_BELOW = 0.9

__all__ = [
    "DOWNGRADE_RATE_BELOW",
    "HIGH_SUCCESS_RATE",
    "LOW_SUCCESS_RATE",
    "MIN_OUTCOMES_FOR_ADJUSTMENT",
    "MIN_OUTCOMES_FOR_DOWNGRADE",
    "MIN_SAMPLES_FOR_DOWNGRADE",
    "MIN_SAMPLES_FOR_RECOMMENDATION",
    "UPGRADE_RATE_BELOW",
    "OutcomeStore",
    "RouterStats",
    "build_router_stats_entry",
    "recommendation_from_stats"]


@dataclass
class OutcomeStore:
    """Outcome store with SQLite restart survival.

    Stats shape (``total`` / ``by_task_type`` / ``by_model``) stays
    evidence-based for routing advice. Rows persist to the shared
    routing database (see :mod:`berg_agents.core.outcome_db`) so
    a restart reloads history instead of starting from zero.

    Attributes:
        outcomes: Raw recorded outcome dicts in arrival order.
        router_stats: Structured router-stats entries in arrival order.
    """

    outcomes: list[dict[str, Any]] = field(default_factory=list)
    router_stats: list[dict[str, Any]] = field(default_factory=list)

    def __init__(
        self,
        outcomes: list[dict[str, Any]] | None = None,
        router_stats: list[dict[str, Any]] | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize the store, reloading persisted rows when available."""
        self._db_path = ensure(db_path)
        self.outcomes = (
            list(outcomes)
            if outcomes is not None
            else load(self._db_path, "outcomes")
        )
        self.router_stats = (
            list(router_stats)
            if router_stats is not None
            else load(self._db_path, "router_stats")
        )

    def record_outcome(
        self,
        task_type: str,
        model: str,
        success: bool,
        user_corrected: bool = False,
        complexity: str = "standard",
    ) -> dict[str, Any]:
        """Record an outcome and return the router-stats summary.

        Args:
            task_type: Task-type label for aggregation.
            model: Model identifier that was used.
            success: Whether the task succeeded.
            user_corrected: Whether the user had to correct it.
            complexity: Complexity label stored on the entry.

        Returns:
            Summary dict with ``status``, ``router_stats``,
            ``stats``, and ``recommendation`` keys.
        """
        # Append the raw outcome before deriving stats so the
        # new sample is included in this call's snapshot.
        outcome = {
            "task_type": task_type,
            "model": model,
            "success": success,
            "user_corrected": user_corrected}
        self.outcomes.append(outcome)
        # Build the structured entry from the same evidence.
        entry = build_router_stats_entry(
            task_type=task_type,
            complexity=complexity,
            model=model,
            success=success,
            user_corrected=user_corrected,
        )
        self.router_stats.append(entry)
        # Persist both rows so a restart reloads this evidence.
        try:
            insert(self._db_path, "outcomes", outcome)
            insert(self._db_path, "router_stats", entry)
        except Exception as exc:
            # Visible, not silent: in-memory stats stay usable, but the
            # write failure must be impossible to miss — a swallowed one
            # is exactly what hid the missing router_stats table.
            logger.warning(
                "OutcomeStore persist failed (in-memory only): %s",
                exc,
                exc_info=True,
            )
        logger.debug("Recorded outcome: %s/%s", task_type, model)
        # Snapshot stats after recording for the caller.
        stats = self.get_outcome_stats()
        return {
            "status": "recorded",
            "router_stats": entry,
            "stats": stats,
            "recommendation": recommendation_from_stats(task_type, stats)}

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
            "by_model": by_model}


def build_router_stats_entry(
    task_type: str,
    complexity: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
) -> dict[str, Any]:
    """Build a structured router-stats entry from an outcome.

    The single entry builder: :meth:`OutcomeStore.record_outcome`,
    :meth:`RouterStats.record`, and any future consumer all use this
    one shape, so the vocabulary never forks again.

    Args:
        task_type: Task-type label for the entry.
        complexity: Complexity label for the entry.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.

    Returns:
        Entry dict with ``task_type``, ``complexity``, ``model``,
        ``success``, ``user_corrected``, ``type``, ``action`` and
        ``detail`` keys.
    """
    # Start from the raw evidence; the derived fields follow below.
    entry: dict[str, Any] = {
        "task_type": task_type,
        "complexity": complexity,
        "model": model,
        "success": success,
        "user_corrected": user_corrected}
    # A user correction outweighs the success flag: the
    # complexity was too low even when the task "succeeded".
    if user_corrected:
        entry["detail"] = (
            f"User correction needed for {task_type} "
            f"with {model}. Consider using a higher-complexity model."
        )
        entry["action"] = "upgrade_complexity"
        entry["type"] = "user_correction"
    elif not success:
        entry["detail"] = (
            f"Task {task_type} failed with {model}. "
            f"Review approach or increase model capability."
        )
        entry["action"] = "review_approach"
        entry["type"] = "failure"
    else:
        entry["detail"] = (
            f"{model} succeeded at {task_type} ({complexity} complexity)."
        )
        entry["action"] = "reinforce"
        entry["type"] = "success"
    return entry


def recommendation_from_stats(
    task_type: str, stats: dict[str, Any]
) -> str | None:
    """Derive a complexity-change recommendation from stats.

    Pure function so thresholds stay testable without running
    the agent.

    Args:
        task_type: Task type to evaluate.
        stats: Outcome-stats dict from ``get_outcome_stats``.

    Returns:
        Recommendation string, or None when evidence is thin or
        the success rate needs no change.
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
        success_rate > DOWNGRADE_RATE_BELOW
        and total >= MIN_SAMPLES_FOR_DOWNGRADE
    ):
        return (
            f"High success rate ({success_rate:.0%}) for "
            f"{task_type}. May downgrade complexity to "
            f"save costs."
        )
    return None


# Default store is created per-facade, not at import: importing this
# module must never open a database (the CLI, tests, and the plugin
# loader all import it).


class RouterStats:
    """Router Dashboard: stats monitor feeding model/agent routing.

    The harness-facing surface. Aggregates outcome stats (counts per
    model/task/agent) used as a dashboard and as input to the router
    self-improvement loop. Learning itself is WHAT/WHY and lives in
    Shared Context (see ADR-0001).

    Responsibilities:

    - Record each outcome once (via :meth:`OutcomeStore.record_outcome`).
    - Build the one insight entry (via :func:`build_router_stats_entry`).
    - Surface routing-adjustment candidates as evidence.
    - Report aggregated stats for the dashboard.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the dashboard, reloading persisted rows if available."""
        self._db_path = ensure(db_path)
        self._store = OutcomeStore(db_path=self._db_path)
        # Best-effort load from SQLite (honors existing stats, not a full replay)
        self._insights: list[dict[str, Any]] = load(
            self._db_path, "router_insights", limit=100
        )
        self._rule_adjustments: list[dict[str, Any]] = load(
            self._db_path, "router_adjustments", limit=20
        )

    def record(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        success: bool,
        user_corrected: bool = False,
    ) -> dict[str, Any]:
        """Record a task outcome and return the insight entry.

        :param task: The task that was executed.
        :param result: Execution result dict.
        :param model_used: Model identifier that was used.
        :param success: Whether the task succeeded.
        :param user_corrected: Whether the user had to correct the agent.
        :return: Insight dict with recommendations for routing
            adjustments, if any.
        """
        task_type = str(task.get("task_type", "unknown"))
        complexity = str(task.get("complexity", "standard"))

        # One store, one builder, one record shape.
        self._store.record_outcome(
            task_type=task_type,
            model=model_used,
            success=success,
            user_corrected=user_corrected,
            complexity=complexity,
        )
        insight = build_router_stats_entry(
            task_type=task_type,
            complexity=complexity,
            model=model_used,
            success=success,
            user_corrected=user_corrected,
        )
        self._insights.append(insight)
        # Persist for restart survival - the single source of truth.
        try:
            insert(self._db_path, "router_insights", insight)
        except Exception as exc:
            logger.warning(
                "router insight persist failed: %s", exc, exc_info=True
            )

        # Check if routing rules should be adjusted
        adjustment = self._evaluate_rules(task)
        if adjustment:
            self._rule_adjustments.append(adjustment)
            insert(self._db_path, "router_adjustments", adjustment)
            self._apply_adjustment(adjustment)
        return insight

    def _evaluate_rules(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate if routing rules should be adjusted from evidence.

        :param task: The task that was executed.
        :return: Adjustment dict if rules should change, None otherwise.
        """
        task_type = str(task.get("task_type", "unknown"))

        by_task = self._store.get_outcome_stats().get("by_task_type", {})
        if task_type not in by_task:
            return None

        task_stats = by_task[task_type]
        total = task_stats["success"] + task_stats["failure"]
        if total < MIN_OUTCOMES_FOR_ADJUSTMENT:
            return None  # Not enough data

        success_rate = task_stats["success"] / total

        if success_rate < LOW_SUCCESS_RATE:
            return {
                "rule": "complexity_upgrade",
                "task_type": task_type,
                "current_rate": success_rate,
                "action": f"Upgrade complexity for {task_type} tasks (success rate: {success_rate:.0%})"}
        if (
            success_rate > HIGH_SUCCESS_RATE
            and total >= MIN_OUTCOMES_FOR_DOWNGRADE
        ):
            return {
                "rule": "complexity_downgrade",
                "task_type": task_type,
                "current_rate": success_rate,
                "action": f"Consider downgrading complexity for {task_type} (success rate: {success_rate:.0%})"}
        return None

    @staticmethod
    def _apply_adjustment(adjustment: dict[str, Any]) -> None:
        """Record a routing-adjustment candidate (does not mutate rules).

        :param adjustment: The candidate to log.
        """
        # record() already appended this adjustment; applying is a
        # no-op beyond the log. Real adaptation is NOT pure outcome
        # statistics — that lever was removed on purpose. It belongs to
        # the Shared Context learning model (WHAT/WHY) and the router
        # self-improvement loop. See notes/tooling-and-router.md §3,
        # decisions/0001-tooling-roles.md, and the 2026-10-28 entries in
        # decisions/decisions-log.md.
        logger.info("Routing adjustment candidate: %s", adjustment["action"])

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive router statistics.

        Returns:
            Dict with all router stats.
        """
        return {
            **self._store.get_outcome_stats(),
            "total_insights": len(self._insights),
            "rule_adjustments": len(self._rule_adjustments),
            "recent_insights": self._insights[-10:],
            "recent_adjustments": self._rule_adjustments[-5:]}
