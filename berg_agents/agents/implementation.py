"""Implementation agent for berg_agents.

Executes code changes with model selected by the router.
Supports file operations, test execution, and error handling.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.interface import AbstractAgent, AgentResult, TaskContext
from berg_agents.core.model_router import ModelRouter

logger = logging.getLogger(__name__)


class Implementation(AbstractAgent):
    """Implementation agent — executes code changes.

    Uses the ModelRouter to select the right model for the task
    complexity. Supports file operations and reports results.
    """

    name: str = "implementation"
    description = "Executes code changes and file operations"
    preferred_model_tier: str = "small"
    capabilities: list[str] = [
        "file_read",
        "file_write",
        "file_edit",
        "file_delete",
        "test_execution",
        "code_generation",
    ]

    def __init__(self, router: ModelRouter | None = None) -> None:
        """Initialize the Implementation agent.

        Args:
            router: Optional ModelRouter for model selection.
        """
        self.router = router or ModelRouter()

    def can_handle(self, task: dict[str, Any]) -> float:
        """Implementation handles code execution tasks.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score based on task type.
        """
        task_type = task.get("task_type", "")

        executable_types = {
            "edit_file",
            "new_file",
            "read_file",
            "delete_file",
            "generate_test",
            "format_code",
            "execute_command",
            "refactor",
            "implement",
            "fix",
        }

        if task_type in executable_types:
            return 0.95

        description = task.get("description", "").lower()
        execution_keywords = [
            "write",
            "edit",
            "create",
            "modify",
            "delete",
            "run",
            "execute",
            "implement",
        ]
        if any(kw in description for kw in execution_keywords):
            return 0.7

        return 0.1

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Execute the code change task.

        In a full implementation, this would use the model and tools
        to perform actual file operations. Here we provide the routing
        and planning logic.

        Args:
            task: Task dictionary with operation details.
            context: Task context with complexity info.
            model: Optional chat model for code generation.

        Returns:
            AgentResult with execution status.
        """
        task_type = task.get("task_type", "generic")
        description = task.get("description", "")

        # Select model based on complexity
        model_config = self.router.select_model(
            context.complexity,
            agent_tier=self.preferred_model_tier,
        )

        # Build execution plan
        execution_plan = self._build_execution_plan(task, context)

        return AgentResult(
            success=True,
            output={
                "status": "planned",
                "task_type": task_type,
                "model_tier": model_config["tier"],
                "models_available": model_config["models"],
                "execution_plan": execution_plan,
                "description": description,
            },
            model_used=model_config["models"][0]
            if model_config["models"]
            else None,
            metadata={
                "complexity": context.complexity.value,
                "requires_tools": self._requires_tools(task_type),
            },
        )

    def _build_execution_plan(
        self, task: dict[str, Any], context: TaskContext
    ) -> list[dict[str, Any]]:
        """Build a step-by-step execution plan for the task.

        Args:
            task: Task dictionary.
            context: Task context.

        Returns:
            List of execution steps.
        """
        task_type = task.get("task_type", "generic")
        steps: list[dict[str, Any]] = []

        if task_type == "edit_file":
            steps = [
                {
                    "action": "read_file",
                    "description": "Read current file content",
                },
                {
                    "action": "analyze",
                    "description": "Analyze required changes",
                },
                {"action": "apply_edit", "description": "Apply the edit"},
                {
                    "action": "verify",
                    "description": "Verify the change is correct",
                },
            ]
        elif task_type == "new_file":
            steps = [
                {
                    "action": "check_exists",
                    "description": "Check if file already exists",
                },
                {"action": "create_file", "description": "Create the new file"},
                {"action": "populate", "description": "Write initial content"},
            ]
        elif task_type == "delete_file":
            steps = [
                {
                    "action": "confirm",
                    "description": "Confirm deletion is safe",
                },
                {
                    "action": "backup_check",
                    "description": "Check for dependencies",
                },
                {"action": "delete", "description": "Delete the file"},
            ]
        elif task_type == "generate_test":
            steps = [
                {
                    "action": "read_source",
                    "description": "Read source code to test",
                },
                {
                    "action": "analyze_coverage",
                    "description": "Identify untested paths",
                },
                {"action": "generate", "description": "Generate test cases"},
                {"action": "write_test", "description": "Write test file"},
            ]
        else:
            steps = [
                {"action": "analyze", "description": "Analyze the task"},
                {"action": "execute", "description": "Execute the operation"},
                {"action": "verify", "description": "Verify the result"},
            ]

        return steps

    def _requires_tools(self, task_type: str) -> list[str]:
        """Determine which tools are needed for a task type.

        Args:
            task_type: Type of task.

        Returns:
            List of required tool names.
        """
        tool_map: dict[str, list[str]] = {
            "edit_file": ["read_file", "edit_file"],
            "new_file": ["new_file"],
            "read_file": ["read_file"],
            "delete_file": ["delete_file"],
            "generate_test": ["read_file", "new_file"],
            "format_code": ["read_file", "edit_file"],
            "execute_command": ["execute_command"],
        }
        return tool_map.get(task_type, ["general"])
