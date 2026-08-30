"""Curator agent for berg_agents.

Updates documentation, manages memory and context files,
distills learnings from completed tasks, and keeps project knowledge fresh.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    TaskComplexity,
    TaskContext,
)

logger = logging.getLogger(__name__)


class Curator(AbstractAgent):
    """Curator agent — manages documentation and memory.

    After tasks complete, the Curator:
    - Updates relevant documentation
    - Records learnings in context files
    - Maintains project knowledge freshness
    - Distills patterns from completed work
    """

    name: str = "curator"
    description = "Updates documentation and manages project memory"
    preferred_model_tier: str = "small"
    capabilities: list[str] = [
        "documentation_update",
        "memory_management",
        "pattern_distilling",
        "context_sync",
    ]

    def __init__(self) -> None:
        """Initialize the Curator."""
        self._update_log: list[dict[str, Any]] = []

    def can_handle(self, task: dict[str, Any]) -> float:
        """Curator handles documentation and memory tasks.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score based on task type.
        """
        task_type = task.get("task_type", "")

        curation_types = {
            "update_docs",
            "document",
            "memory_update",
            "context_sync",
            "distill",
            "summarize",
            "curate",
        }

        if task_type in curation_types:
            return 1.0

        description = task.get("description", "").lower()
        curation_keywords = [
            "document",
            "update readme",
            "update docs",
            "memory",
            "context",
        ]
        if any(kw in description for kw in curation_keywords):
            return 0.7

        return 0.1

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Execute documentation/memory curation.

        Args:
            task: Task dictionary with curation details.
            context: Task context.
            model: Optional model for content generation.

        Returns:
            AgentResult with curation actions taken.
        """
        task_type = task.get("task_type", "generic")
        description = task.get("description", "")

        # Determine what to update
        actions = self._determine_actions(task, context)

        # Build update plan
        update_plan = self._build_update_plan(actions, context)

        return AgentResult(
            success=True,
            output={
                "status": "curated",
                "actions": actions,
                "update_plan": update_plan,
                "files_to_update": [a.get("target", "") for a in actions],
            },
            metadata={
                "task_type": task_type,
                "complexity": context.complexity.value,
            },
        )

    def _determine_actions(
        self, task: dict[str, Any], context: TaskContext
    ) -> list[dict[str, Any]]:
        """Determine what curation actions are needed.

        Args:
            task: Task dictionary.
            context: Task context.

        Returns:
            List of action descriptors.
        """
        actions: list[dict[str, Any]] = []
        task_type = task.get("task_type", "generic")
        metadata = context.metadata

        # Check if there are code changes to document
        if "files_changed" in metadata:
            for filepath in metadata["files_changed"]:
                actions.append({
                    "action": "update_docs",
                    "target": filepath,
                    "type": "code_documentation",
                })

        # Check if there are new patterns to record
        if "patterns" in metadata:
            for pattern in metadata["patterns"]:
                actions.append({
                    "action": "record_pattern",
                    "target": "context/examples/",
                    "type": "pattern",
                    "content": pattern,
                })

        # Check if decisions were made
        if "decisions" in metadata:
            for decision in metadata["decisions"]:
                actions.append({
                    "action": "record_decision",
                    "target": "decisions/decisions-log.md",
                    "type": "decision",
                    "content": decision,
                })

        # Default: update technical domain if task was complex
        if not actions and context.complexity in (
            TaskComplexity.COMPLEX,
            TaskComplexity.CRITICAL,
        ):
            actions.append({
                "action": "update_context",
                "target": "context/technical-domain.md",
                "type": "knowledge_update",
            })

        return actions

    def _build_update_plan(
        self, actions: list[dict[str, Any]], context: TaskContext
    ) -> list[dict[str, Any]]:
        """Build an ordered plan for applying updates.

        Args:
            actions: List of curation actions.
            context: Task context.

        Returns:
            Ordered list of update steps.
        """
        plan: list[dict[str, Any]] = []

        # Group by type
        doc_actions = [a for a in actions if a["type"] == "code_documentation"]
        pattern_actions = [a for a in actions if a["type"] == "pattern"]
        decision_actions = [a for a in actions if a["type"] == "decision"]
        knowledge_actions = [
            a for a in actions if a["type"] == "knowledge_update"
        ]

        # Order: docs first, then patterns, then decisions, then knowledge
        for action in doc_actions:
            plan.append({
                "step": len(plan) + 1,
                "action": "update",
                "target": action["target"],
                "description": f"Update documentation for {action['target']}",
            })

        for action in pattern_actions:
            plan.append({
                "step": len(plan) + 1,
                "action": "append",
                "target": action["target"],
                "description": f"Record new pattern: {action.get('content', '')[:50]}",
            })

        for action in decision_actions:
            plan.append({
                "step": len(plan) + 1,
                "action": "append",
                "target": action["target"],
                "description": "Record architecture decision",
            })

        for action in knowledge_actions:
            plan.append({
                "step": len(plan) + 1,
                "action": "update",
                "target": action["target"],
                "description": "Update technical domain knowledge",
            })

        return plan

    def get_update_log(self) -> list[dict[str, Any]]:
        """Return the log of all updates made.

        Returns:
            List of update log entries.
        """
        return list(self._update_log)
