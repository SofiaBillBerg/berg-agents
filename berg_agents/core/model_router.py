"""Model router for berg_agents.

Selects the right model tier based on task complexity.
Feeds outcome data to the learning gate for adaptive improvement.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from berg_agents.core.interface import TaskComplexity

logger = logging.getLogger(__name__)

# Default complexity rules — can be overridden from bergagents.jsonc
DEFAULT_COMPLEXITY_RULES: dict[str, dict[str, Any]] = {
    "trivial": {
        "patterns": [
            r"^read\s+file",
            r"^list\s+files",
            r"^search",
            r"^show",
            r"^display",
            r"^print",
            r"^get\s+",
            r"^check\s+",
            r"^find\s+",
            r"^cat\s+",
            r"^ls$",
            r"^pwd$",
            r"^help",
        ],
        "keywords": [
            "read",
            "list",
            "show",
            "display",
            "print",
            "get",
            "check",
            "find",
            "search",
            "help",
        ],
        "tier": "small",
    },
    "standard": {
        "patterns": [
            r"^edit\s+file",
            r"^new\s+file",
            r"^create\s+file",
            r"^update\s+",
            r"^write\s+",
            r"^add\s+test",
            r"^generate\s+test",
            r"^format\s+",
            r"^refactor\s+single",
        ],
        "keywords": [
            "edit",
            "update",
            "write",
            "create",
            "add",
            "test",
            "format",
            "modify",
            "change",
        ],
        "tier": "small",
    },
    "complex": {
        "patterns": [
            r"^refactor",
            r"^architecture",
            r"^multi.file",
            r"^multi_file",
            r"^redesign",
            r"^migrate",
            r"^integrate",
            r"^optimize\s+performance",
            r"^implement\s+feature",
        ],
        "keywords": [
            "refactor",
            "architecture",
            "redesign",
            "migrate",
            "integrate",
            "optimize",
            "implement",
            "design",
        ],
        "tier": "large",
    },
    "critical": {
        "patterns": [
            r"^delete",
            r"^remove\s+all",
            r"^security",
            r"^production",
            r"^deploy",
            r"^database\s+migration",
            r"^credentials?",
            r"^api\s+key",
            r"^password",
        ],
        "keywords": [
            "delete",
            "remove",
            "security",
            "production",
            "deploy",
            "migration",
            "credentials",
            "password",
        ],
        "tier": "large",
        "human_review": True,
    },
}

# Default model tier configuration
DEFAULT_TIER_CONFIG: dict[str, dict[str, Any]] = {
    "small": {
        "models": ["qwen3.5:9b", "llama3.2:3b"],
        "max_tokens": 4096,
        "description": "Fast, cheap models for simple tasks",
    },
    "medium": {
        "models": ["gpt-oss:20b", "qwen3.5:32b"],
        "max_tokens": 8192,
        "description": "Balanced models for moderate tasks",
    },
    "large": {
        "models": ["gpt-4o", "claude-sonnet-4-20250514"],
        "max_tokens": 128000,
        "description": "Powerful models for complex tasks",
    },
}


class ModelRouter:
    """Selects the right model tier based on task complexity.

    The router estimates complexity from the task description,
    maps it to a model tier, and can record outcomes for learning.

    Usage:
        router = ModelRouter()
        complexity = router.estimate_complexity(task)
        model_config = router.select_model(complexity, agent_tier="medium")
    """

    def __init__(
        self,
        complexity_rules: dict[str, dict[str, Any]] | None = None,
        tier_config: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the model router.

        Args:
            complexity_rules: Custom complexity rules (merges with defaults).
            tier_config: Custom tier configuration (merges with defaults).
        """
        self.complexity_rules = {
            **DEFAULT_COMPLEXITY_RULES,
            **(complexity_rules or {}),
        }
        self.tier_config = {**DEFAULT_TIER_CONFIG, **(tier_config or {})}
        self._outcome_log: list[dict[str, Any]] = []

    def estimate_complexity(self, task: dict[str, Any]) -> TaskComplexity:
        """Estimate task complexity from description and type.

        Scores each complexity level based on pattern and keyword matches.
        Returns the highest matching level, defaulting to STANDARD.

        Args:
            task: Task dictionary with 'description' and optionally 'task_type'.

        Returns:
            TaskComplexity enum value.
        """
        description = task.get("description", "").lower().strip()
        task_type = task.get("task_type", "").lower().strip()
        combined = f"{task_type} {description}".strip()

        # Score each complexity level
        scores: dict[str, int] = {
            "trivial": 0,
            "standard": 0,
            "complex": 0,
            "critical": 0,
        }

        for level, rules in self.complexity_rules.items():
            # Pattern matching (higher weight)
            for pattern in rules.get("patterns", []):
                if re.search(pattern, combined, re.IGNORECASE):
                    scores[level] = scores.get(level, 0) + 3

            # Keyword matching (lower weight)
            for keyword in rules.get("keywords", []):
                if keyword in combined:
                    scores[level] = scores.get(level, 0) + 1

        # Critical always wins if matched (highest priority)
        if scores.get("critical", 0) > 0:
            return TaskComplexity.CRITICAL

        # Return highest scoring level above threshold
        max_level = "standard"  # default
        max_score = 0
        for level in ["complex", "trivial", "standard"]:
            if scores.get(level, 0) > max_score:
                max_score = scores[level]
                max_level = level

        if max_score == 0:
            return TaskComplexity.STANDARD

        return TaskComplexity(max_level)

    def select_model(
        self,
        complexity: TaskComplexity | str,
        agent_tier: str = "small",
    ) -> dict[str, Any]:
        """Select model configuration based on complexity and agent preference.

        Args:
            complexity: Estimated complexity (enum or string).
            agent_tier: Agent's preferred tier ("small", "medium", "large").

        Returns:
            Model configuration dict with models, max_tokens, tier info.
        """
        if isinstance(complexity, str):
            complexity = TaskComplexity(complexity)

        # Map complexity to tier
        complexity_tier_map = {
            TaskComplexity.TRIVIAL: "small",
            TaskComplexity.STANDARD: "small",
            TaskComplexity.COMPLEX: "large",
            TaskComplexity.CRITICAL: "large",
        }

        target_tier = complexity_tier_map[complexity]

        # Agent preference can upgrade but not downgrade below task requirement
        tier_priority = {"small": 0, "medium": 1, "large": 2}
        if tier_priority.get(agent_tier, 0) > tier_priority.get(target_tier, 0):
            target_tier = agent_tier

        tier_info = self.tier_config.get(
            target_tier, self.tier_config["medium"]
        )

        return {
            "tier": target_tier,
            "models": tier_info["models"],
            "max_tokens": tier_info["max_tokens"],
            "complexity": complexity.value,
            "human_review_required": self.complexity_rules.get(
                complexity.value, {}
            ).get("human_review", False),
        }

    def record_outcome(
        self,
        task: dict[str, Any],
        model: str,
        success: bool,
        user_corrected: bool = False,
    ) -> None:
        """Record task outcome for learning gate integration.

        Args:
            task: The task that was executed.
            model: Model identifier that was used.
            success: Whether the task succeeded.
            user_corrected: Whether the user had to correct the agent.
        """
        entry = {
            "task_type": task.get("task_type", "unknown"),
            "description": task.get("description", ""),
            "model": model,
            "success": success,
            "user_corrected": user_corrected,
        }
        self._outcome_log.append(entry)
        logger.debug("Recorded outcome: %s", entry)

    def get_outcome_stats(self) -> dict[str, Any]:
        """Get aggregated outcome statistics.

        Returns:
            Dict with success rates per task type and model.
        """
        if not self._outcome_log:
            return {"total": 0, "by_task_type": {}, "by_model": {}}

        by_task_type: dict[str, dict[str, int]] = {}
        by_model: dict[str, dict[str, int]] = {}

        for entry in self._outcome_log:
            task_type = entry["task_type"]
            model = entry["model"]

            if task_type not in by_task_type:
                by_task_type[task_type] = {"success": 0, "failure": 0}
            by_task_type[task_type][
                "success" if entry["success"] else "failure"
            ] += 1

            if model not in by_model:
                by_model[model] = {"success": 0, "failure": 0}
            by_model[model]["success" if entry["success"] else "failure"] += 1

        return {
            "total": len(self._outcome_log),
            "by_task_type": by_task_type,
            "by_model": by_model,
        }
