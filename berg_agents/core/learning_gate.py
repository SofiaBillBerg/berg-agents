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

from berg_agents.agents.learning import get_outcome_stats, record_outcome
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


def _store_in_mempalace(insight: dict[str, Any]) -> None:
    """No-op: MemPalace is not an automatic log.

    Diary entries are written manually by the agent when it has
    something genuinely worth recording — never on a schedule or
    per-task outcome. This function exists as the single call site
    and is intentionally empty.

    :param insight: Unused.
    """
    return


class LearningGate:
    """Central learning system that adapts BergAgents over time.

    The Learning Gate observes all task outcomes and:
    - Tracks which models work best for which tasks
    - Identifies patterns in success/failure
    - Updates routing rules to improve future decisions
    - Stores long-term learnings in MemPalace knowledge graph
    """

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the Learning Gate — loads persisted insights if available."""
        self._db_path = ensure(db_path)
        # Best-effort load from SQLite (honors existing OutcomeStore stats, not a full replay)
        self._insights: list[dict[str, Any]] = load(
            self._db_path, "learning_insights", limit=100
        )
        self._rule_adjustments: list[dict[str, Any]] = load(
            self._db_path, "learning_adjustments", limit=20
        )

    def record(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        success: bool,
        user_corrected: bool = False,
    ) -> dict[str, Any]:
        """Record a task outcome and generate insights.


        :param task: The task that was executed.
        :param result: Execution result dict.
        :param model_used: Model identifier that was used.
        :param success: Whether the task succeeded.
        :param user_corrected: Whether the user had to correct the agent.

        :return: Insight dict with learning and recommendations.
        """
        # Record in the shared outcome store.
        record_outcome(
            task_type=str(task.get("task_type", "unknown")),
            model=model_used,
            success=success,
            user_corrected=user_corrected,
            complexity=str(task.get("complexity", "standard")),
        )

        # Generate insight. Runs that never touched a model
        # (greetings, gated tasks) carry no signal worth
        # remembering, so they skip the MemPalace write.
        insight = self._create_insight(
            task,
            model_used,
            success,
            user_corrected,
            store_memory=bool(result.get("inference_attempted", True)),
        )

        # Check if routing rules should be adjusted
        adjustment = self._evaluate_rules(task)
        if adjustment:
            self._rule_adjustments.append(adjustment)
            insert(self._db_path, "learning_adjustments", adjustment)
            self._apply_adjustment(adjustment)
            # A routing rule actually changed — that IS worth
            # remembering; hand it to the moderated MemPalace write.
            adj_insight = {
                "type": "adjustment",
                "task_type": adjustment.get("task_type"),
                "message": (
                    "Routing adjusted: "
                    f"{adjustment.get('action', 'updated')} for "
                    f"{adjustment.get('task_type', 'unknown')} "
                    f"(reason: {adjustment.get('reason', 'stats')})"
                ),
                "topic": "learning_gate"}
            _store_in_mempalace(adj_insight)

        return insight

    def _create_insight(
        self,
        task: dict[str, Any],
        model: str,
        success: bool,
        user_corrected: bool,
        store_memory: bool = True,
    ) -> dict[str, Any]:
        """Create a structured insight from an outcome.

        :param task: The task that was executed.
        :param model: Model used.
        :param success: Whether it succeeded.
        :param user_corrected: Whether user corrected.
        :param store_memory: Persist to MemPalace; False for
            model-free runs (greetings, gated tasks) with
            no signal worth remembering.
        :return:            Insight dict.
        """
        task_type = task.get("task_type", "unknown")
        complexity = task.get("complexity", "standard")

        if user_corrected:
            insight = {
                "type": "user_correction",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "upgrade_complexity",
                "message": f"User correction for {task_type} with {model}. Consider higher complexity."}
        elif not success:
            insight = {
                "type": "failure",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "review",
                "message": f"{task_type} failed with {model}. Review approach."}
        else:
            insight = {
                "type": "success",
                "task_type": task_type,
                "complexity": complexity,
                "model": model,
                "action": "reinforce",
                "message": f"{model} succeeded at {task_type} ({complexity})."}
        self._insights.append(insight)
        # Persist to SQLite for restart survival — the single source of truth.
        try:
            import datetime
            import json
            import sqlite3

            con = sqlite3.connect(self._db_path)
            con.execute(
                "INSERT INTO learning_insights (ts, data) VALUES (?, ?)",
                (
                    datetime.datetime.now(datetime.UTC).isoformat(),
                    json.dumps(insight, default=str),
                ),
            )
            con.commit()
            con.close()
        except Exception as exc:
            logger.debug("learning_gate persist insight failed: %s", exc)
        if store_memory:
            # Autosave = mempalace only, for genuine insights.
            # notes/learning_log.md is for the agent to write
            # meaningful notes when it chooses — not an
            # automatically appended stream.
            _store_in_mempalace(insight)
        return insight

    @staticmethod
    def _evaluate_rules(task: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate if routing rules should be adjusted.

        :param task: The task that was executed.
        :return: Adjustment dict if rules should change, None otherwise.
        """
        stats = get_outcome_stats()
        task_type = task.get("task_type", "unknown")

        by_task = stats.get("by_task_type", {})
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
        elif (
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
        """Apply a routing rule adjustment.

        :param adjustment: The adjustment to apply.
        """
        # record() already appended this adjustment; applying is
        # currently a no-op beyond the log because routing reads
        # live outcome stats, not this list.
        logger.info("Learning Gate adjustment: %s", adjustment["action"])

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive learning statistics.

        Returns:
            Dict with all learning stats.
        """
        outcome_stats = get_outcome_stats()
        return {
            **outcome_stats,
            "total_insights": len(self._insights),
            "rule_adjustments": len(self._rule_adjustments),
            "recent_insights": self._insights[-10:],
            "recent_adjustments": self._rule_adjustments[-5:]}
