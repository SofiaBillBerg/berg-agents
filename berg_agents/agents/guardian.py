"""Guardian agent for berg_agents.

Decides when human-in-the-loop review is needed based on:
- Task complexity
- Risk level
- Model confidence
- Historical patterns

The Guardian is the gatekeeper of the human-AI balance principle.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    RiskLevel,
    TaskComplexity,
    TaskContext,
)

logger = logging.getLogger(__name__)

# Risk patterns for automatic high-risk classification
HIGH_RISK_PATTERNS: list[str] = [
    r"delete\s+",
    r"remove\s+all",
    r"drop\s+table",
    r"truncate",
    r"rm\s+-rf",
    r"force\s+push",
    r"overwrite",
    r"production",
    r"deploy",
    r"credentials?",
    r"api[_\s]?key",
    r"secret",
    r"password",
    r"token",
    r"security",
    r"auth",
    r"permission",
    r"database\s+migration",
    r"irreversible",
]

MEDIUM_RISK_PATTERNS: list[str] = [
    r"refactor",
    r"rewrite",
    r"migrate",
    r"upgrade",
    r"downgrade",
    r"install",
    r"uninstall",
    r"configure",
    r"settings?",
    r"environment",
    r"env\s+var",
]


class Guardian(AbstractAgent):
    """Guardian agent — decides when human review is needed.

    The Guardian evaluates tasks based on:
    1. Complexity (trivial → critical)
    2. Risk level (low → critical)
    3. Model confidence (0.0 → 1.0)

    It does NOT execute tasks — it only makes HITL decisions.
    """

    name: str = "guardian"
    description: str = "Decides when human review is needed"
    preferred_model_tier: str = "medium"
    capabilities: list[str] = [
        "hitl_decision",
        "risk_assessment",
        "security_review",
    ]

    def __init__(
        self,
        auto_execute: list[str] | None = None,
        notify_after: list[str] | None = None,
        ask_before: list[str] | None = None,
        human_leads: list[str] | None = None,
    ) -> None:
        """Initialize the Guardian.

        Args:
            auto_execute: Task types that never need human review.
            notify_after: Task types where human is notified after execution.
            ask_before: Task types where human must approve before execution.
            human_leads: Task types where human leads and AI assists.
        """
        self.auto_execute = auto_execute or [
            "read_file",
            "list_files",
            "search_code",
            "show_help",
            "display_content",
        ]
        self.notify_after = notify_after or [
            "edit_file",
            "new_file",
            "generate_test",
            "format_code",
        ]
        self.ask_before = ask_before or [
            "delete_file",
            "execute_command",
            "refactor",
            "install_package",
        ]
        self.human_leads = human_leads or [
            "security_change",
            "production_deploy",
            "data_migration",
        ]

    def can_handle(self, task: dict[str, Any]) -> float:
        """Guardian can assess any task for HITL needs.

        Returns high confidence for all tasks since risk assessment
        is always applicable.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score (0.8 for most tasks).
        """
        return 0.8

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Assess the task and decide if human review is needed.

        Args:
            task: Task dictionary with description and task_type.
            context: Task context with complexity and risk info.
            model: Unused for Guardian (rule-based decisions).

        Returns:
            AgentResult with needs_human_review flag and reasons.
        """
        complexity = context.complexity
        risk = self.assess_risk(task)
        task_type = task.get("task_type", "generic")

        needs_review, reasons = self._decide_hitl(task_type, complexity, risk)

        return AgentResult(
            success=True,
            output={
                "needs_human_review": needs_review,
                "risk_level": risk.value,
                "complexity": complexity.value,
                "reasons": reasons,
                "task_type": task_type,
            },
            needs_human_review=needs_review,
            review_reasons=reasons,
        )

    def assess_risk(self, task: dict[str, Any]) -> RiskLevel:
        """Assess the risk level of a task.

        Analyzes the task description and type against known risk patterns.

        Args:
            task: Task dictionary with 'description' and 'task_type'.

        Returns:
            RiskLevel enum value.
        """
        description = task.get("description", "").lower().strip()
        task_type = task.get("task_type", "").lower().strip()
        combined = f"{task_type} {description}".strip()

        # Check high risk patterns
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                return RiskLevel.HIGH

        # Check medium risk patterns
        for pattern in MEDIUM_RISK_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                return RiskLevel.MEDIUM

        # Task type based risk
        high_risk_types = {
            "delete",
            "deploy",
            "security",
            "production",
            "migration",
        }
        if task_type in high_risk_types:
            return RiskLevel.HIGH

        medium_risk_types = {
            "refactor",
            "install",
            "configure",
            "upgrade",
            "rewrite",
        }
        if task_type in medium_risk_types:
            return RiskLevel.MEDIUM

        return RiskLevel.LOW

    def needs_human_review(
        self,
        task: dict[str, Any],
        complexity: TaskComplexity | str,
        confidence: float = 1.0,
    ) -> tuple[bool, list[str]]:
        """Convenience method: decide if human review is needed.

        Args:
            task: Task dictionary.
            complexity: Task complexity level.
            confidence: Model confidence score (0.0 to 1.0).

        Returns:
            Tuple of (needs_review, list_of_reasons).
        """
        if isinstance(complexity, str):
            complexity = TaskComplexity(complexity)

        risk = self.assess_risk(task)
        task_type = task.get("task_type", "generic")
        return self._decide_hitl(task_type, complexity, risk, confidence)

    def _decide_hitl(
        self,
        task_type: str,
        complexity: TaskComplexity,
        risk: RiskLevel,
        confidence: float = 1.0,
    ) -> tuple[bool, list[str]]:
        """Core HITL decision logic.

        Decision matrix:
        - Critical complexity → always review
        - High risk → always review
        - Low confidence → always review
        - Human-leads task types → always review
        - Ask-before task types → review
        - Auto-execute task types → no review
        - Notify-after → no review (but notify)

        Args:
            task_type: Type of task.
            complexity: Task complexity.
            risk: Assessed risk level.
            confidence: Model confidence (0.0 to 1.0).

        Returns:
            Tuple of (needs_review, reasons).
        """
        reasons: list[str] = []

        # Critical complexity always needs review
        if complexity == TaskComplexity.CRITICAL:
            reasons.append("Critical complexity task")

        # High/Critical risk always needs review
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            reasons.append(f"High risk task: {risk.value}")

        # Low confidence always needs review
        if confidence < 0.6:
            reasons.append(f"Low model confidence: {confidence:.2f}")

        # Task type based decisions
        if task_type in self.human_leads:
            reasons.append(f"Human-leads task type: {task_type}")
        elif task_type in self.ask_before:
            reasons.append(f"Ask-before task type: {task_type}")

        needs_review = len(reasons) > 0

        if not needs_review:
            reasons.append("Auto-execute: low risk, high confidence")

        return needs_review, reasons
