"""Abstract agent interface for berg_agents.

This module defines the contract that every subagent implements.
It is framework-agnostic — no LangChain/LangGraph imports here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class TaskComplexity(str, Enum):
    """Task complexity levels."""

    TRIVIAL = "trivial"
    STANDARD = "standard"
    COMPLEX = "complex"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    """Risk assessment levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskContext:
    """Context for a task being processed."""

    task_id: str
    description: str
    task_type: str = "generic"
    complexity: TaskComplexity = TaskComplexity.STANDARD
    risk_level: RiskLevel = RiskLevel.LOW
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "complexity": self.complexity.value,
            "risk_level": self.risk_level.value,
            "metadata": self.metadata,
        }


@dataclass
class AgentResult:
    """Standardized result from agent execution."""

    success: bool
    output: Any = None
    error: str | None = None
    needs_human_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    model_used: str | None = None
    tokens_used: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "needs_human_review": self.needs_human_review,
            "review_reasons": self.review_reasons,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "metadata": self.metadata,
        }


class AbstractAgent(ABC):
    """Base class for all berg_agents subagents.

    Every subagent must implement:
    - can_handle(task) -> float: Return confidence 0-1
    - execute(task, context, model) -> AgentResult: Execute the task

    Subagents declare their preferred model tier and capabilities.
    The orchestrator uses this to route tasks.
    """

    name: str = "abstract_agent"
    description: str = "Base agent class"
    preferred_model_tier: str = "medium"  # "small", "medium", "large"
    capabilities: list[str] = []

    @abstractmethod
    def can_handle(self, task: dict[str, Any]) -> float:
        """Return confidence 0-1 that this agent can handle the task.

        Args:
            task: Task dictionary with at least 'description' and 'task_type' keys.

        Returns:
            Float between 0.0 (cannot handle) and 1.0 (perfect match).
        """
        ...

    @abstractmethod
    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Execute the task.

        Args:
            task: Task dictionary with task details.
            context: TaskContext with metadata and routing info.
            model: Optional chat model instance (provider-agnostic).

        Returns:
            AgentResult with success status and output.
        """
        ...

    def get_info(self) -> dict[str, Any]:
        """Return agent info for registry and debugging."""
        return {
            "name": self.name,
            "description": self.description,
            "preferred_model_tier": self.preferred_model_tier,
            "capabilities": self.capabilities,
        }
