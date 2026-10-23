# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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


def _adjustment_direction(adjustment: dict[str, Any]) -> str | None:
    """Map an adjustment's rule to a routing direction.

    :param adjustment: Adjustment dict produced by ``_evaluate_rules``.
    :return: ``"up"`` for a complexity upgrade, ``"down"`` for a
        downgrade, or None when the rule is not a routing rule.
    """
    rule = str(adjustment.get("rule", ""))
    if "upgrade" in rule:
        return "up"
    if "downgrade" in rule:
        return "down"
    return None


def _store_in_mempalace(insight: dict[str, Any]) -> None:
    """No-op: MemPalace is not an automatic log.

    Diary entries are written manually by the agent when it has
    something genuinely worth recording - never on a schedule or
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
        """Initialize the Learning Gate - loads persisted insights if available."""
        self._db_path = ensure(db_path)
        # Best-effort load from SQLite (honors existing OutcomeStore stats, not a full replay)
        self._insights: list[dict[str, Any]] = load(
            self._db_path, "learning_insights", limit=100
        )
        self._rule_adjustments: list[dict[str, Any]] = load(
            self._db_path, "learning_adjustments", limit=20
        )
        # Complexity-direction overrides routing consults:
        # task_type -> "up" | "down", latest adjustment winning. Rebuilt
        # here from persisted adjustments so a restart restores routing,
        # not just the stats.
        self._complexity_overrides: dict[str, str] = {}
        for adjustment in self._rule_adjustments:
            direction = _adjustment_direction(adjustment)
            task_type = adjustment.get("task_type")
            if direction and task_type:
                self._complexity_overrides[str(task_type)] = direction

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
            # A routing rule actually changed - that IS worth
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
        # Persist to SQLite for restart survival - the single source of truth.
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
            # meaningful notes when it chooses - not an
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

    def _apply_adjustment(self, adjustment: dict[str, Any]) -> None:
        """Apply a routing-rule adjustment as a complexity direction.

        ``record`` already persisted this adjustment to
        ``learning_adjustments``; applying it means routing will consult
        the direction. Register the per-task-type override so
        :meth:`complexity_override` can hand it to the router on the
        next task of that type.

        :param adjustment: The adjustment to apply.
        """
        direction = _adjustment_direction(adjustment)
        task_type = adjustment.get("task_type")
        if direction and task_type:
            self._complexity_overrides[str(task_type)] = direction
            logger.info(
                "Learning Gate applied %s complexity for %s (%s)",
                direction,
                task_type,
                adjustment.get("action"),
            )
        else:
            logger.info(
                "Learning Gate adjustment (no routing effect): %s",
                adjustment.get("action"),
            )

    def complexity_override(self, task_type: str) -> str | None:
        """Return the learned routing direction for a task type.

        Routing consults this to shift complexity (moving the resolved
        model tier with the evidence). See
        :func:`berg_agents.core.harness._routing._shift_complexity`.

        :param task_type: Task type being routed.
        :return: ``"up"``, ``"down"``, or None when no rule applies.
        """
        return self._complexity_overrides.get(task_type)

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
