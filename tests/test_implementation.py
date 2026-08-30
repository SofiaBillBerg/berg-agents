"""Tests for berg_agents.agents.implementation — code execution."""

import pytest

from berg_agents.agents.implementation import Implementation
from berg_agents.core.interface import TaskComplexity, TaskContext


@pytest.fixture
def impl() -> Implementation:
    return Implementation()


# ── can_handle ──────────────────────────────────────────────────


class TestCanHandle:
    def test_edit_file_returns_high_confidence(
        self, impl: Implementation
    ) -> None:
        assert (
            impl.can_handle({"task_type": "edit_file", "description": "x"})
            == 0.95
        )

    def test_new_file_returns_high_confidence(
        self, impl: Implementation
    ) -> None:
        assert (
            impl.can_handle({"task_type": "new_file", "description": "x"})
            == 0.95
        )

    def test_delete_file_returns_high_confidence(
        self, impl: Implementation
    ) -> None:
        assert (
            impl.can_handle({"task_type": "delete_file", "description": "x"})
            == 0.95
        )

    def test_generic_returns_low_confidence(self, impl: Implementation) -> None:
        assert (
            impl.can_handle({"task_type": "generic", "description": "x"}) == 0.1
        )

    def test_description_with_keyword(self, impl: Implementation) -> None:
        confidence = impl.can_handle({
            "task_type": "generic",
            "description": "write a function",
        })
        assert confidence >= 0.7


# ── Execute ─────────────────────────────────────────────────────


class TestExecute:
    def test_execute_returns_success(self, impl: Implementation) -> None:
        task = {"description": "edit file main.py", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="edit_file"
        )
        result = impl.execute(task, ctx)
        assert result.success is True
        assert result.output["status"] == "planned"

    def test_model_tier_selected_for_complex(
        self, impl: Implementation
    ) -> None:
        task = {"description": "refactor auth", "task_type": "refactor"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="refactor",
            complexity=TaskComplexity.COMPLEX,
        )
        result = impl.execute(task, ctx)
        assert result.output["model_tier"] == "large"

    def test_model_tier_for_trivial(self, impl: Implementation) -> None:
        task = {"description": "read file", "task_type": "read_file"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="read_file",
            complexity=TaskComplexity.TRIVIAL,
        )
        result = impl.execute(task, ctx)
        assert result.output["model_tier"] == "small"

    def test_execution_plan_populated(self, impl: Implementation) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="edit_file"
        )
        result = impl.execute(task, ctx)
        assert len(result.output["execution_plan"]) > 0
        assert all("action" in step for step in result.output["execution_plan"])

    def test_models_available_populated(self, impl: Implementation) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="edit_file"
        )
        result = impl.execute(task, ctx)
        assert len(result.output["models_available"]) > 0


# ── Execution plans ─────────────────────────────────────────────


class TestExecutionPlans:
    def test_edit_file_plan(self, impl: Implementation) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="edit_file"
        )
        result = impl.execute(task, ctx)
        steps = result.output["execution_plan"]
        actions = [s["action"] for s in steps]
        assert "read_file" in actions
        assert "apply_edit" in actions

    def test_new_file_plan(self, impl: Implementation) -> None:
        task = {"description": "new file", "task_type": "new_file"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="new_file"
        )
        result = impl.execute(task, ctx)
        steps = result.output["execution_plan"]
        actions = [s["action"] for s in steps]
        assert "create_file" in actions

    def test_delete_file_plan(self, impl: Implementation) -> None:
        task = {"description": "delete file", "task_type": "delete_file"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="delete_file",
        )
        result = impl.execute(task, ctx)
        steps = result.output["execution_plan"]
        actions = [s["action"] for s in steps]
        assert "confirm" in actions
