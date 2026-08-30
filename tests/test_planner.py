"""Tests for berg_agents.agents.planner — task decomposition."""

import pytest

from berg_agents.agents.planner import Planner, Subtask
from berg_agents.core.interface import TaskComplexity, TaskContext


@pytest.fixture
def planner() -> Planner:
    return Planner()


# ── can_handle ──────────────────────────────────────────────────


class TestCanHandle:
    def test_plan_task_type_returns_full_confidence(
        self, planner: Planner
    ) -> None:
        assert (
            planner.can_handle({"task_type": "plan", "description": "anything"})
            == 1.0
        )

    def test_decompose_task_type(self, planner: Planner) -> None:
        assert (
            planner.can_handle({"task_type": "decompose", "description": "x"})
            == 1.0
        )

    def test_complex_task_returns_high_confidence(
        self, planner: Planner
    ) -> None:
        confidence = planner.can_handle({
            "task_type": "refactor",
            "description": "refactor the authentication system",
        })
        assert confidence >= 0.8

    def test_trivial_task_returns_low_confidence(
        self, planner: Planner
    ) -> None:
        confidence = planner.can_handle({
            "task_type": "read_file",
            "description": "read file main.py",
        })
        assert confidence <= 0.3


# ── Decomposition ───────────────────────────────────────────────


class TestDecompose:
    def test_refactor_produces_multiple_subtasks(
        self, planner: Planner
    ) -> None:
        task = {
            "description": "refactor the auth module",
            "task_type": "refactor",
        }
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="refactor"
        )
        result = planner.execute(task, ctx)
        assert result.success is True
        assert result.output["total_subtasks"] >= 3

    def test_implement_produces_subtasks(self, planner: Planner) -> None:
        task = {
            "description": "implement new feature",
            "task_type": "implement",
        }
        ctx = TaskContext(
            task_id="t2", description=task["description"], task_type="implement"
        )
        result = planner.execute(task, ctx)
        assert result.success is True
        assert result.output["total_subtasks"] >= 2

    def test_fix_produces_subtasks(self, planner: Planner) -> None:
        task = {"description": "fix the bug in parser", "task_type": "fix"}
        ctx = TaskContext(
            task_id="t3", description=task["description"], task_type="fix"
        )
        result = planner.execute(task, ctx)
        assert result.success is True
        assert result.output["total_subtasks"] >= 2

    def test_generic_task_produces_single_subtask(
        self, planner: Planner
    ) -> None:
        task = {"description": "do something simple", "task_type": "generic"}
        ctx = TaskContext(
            task_id="t4", description=task["description"], task_type="generic"
        )
        result = planner.execute(task, ctx)
        assert result.success is True
        assert result.output["total_subtasks"] == 1


# ── Subtask structure ───────────────────────────────────────────


class TestSubtaskStructure:
    def test_subtasks_have_ids(self, planner: Planner) -> None:
        task = {"description": "refactor module", "task_type": "refactor"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="refactor"
        )
        result = planner.execute(task, ctx)
        for subtask in result.output["subtasks"]:
            assert "id" in subtask
            assert "description" in subtask
            assert "complexity" in subtask

    def test_subtasks_have_model_tier(self, planner: Planner) -> None:
        task = {"description": "refactor module", "task_type": "refactor"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="refactor"
        )
        result = planner.execute(task, ctx)
        for subtask in result.output["subtasks"]:
            assert "estimated_model_tier" in subtask
            assert subtask["estimated_model_tier"] in (
                "small",
                "medium",
                "large",
            )

    def test_dependency_order_is_correct(self, planner: Planner) -> None:
        """Subtasks should be topologically sorted (dependencies come first)."""
        task = {"description": "refactor module", "task_type": "refactor"}
        ctx = TaskContext(
            task_id="t1", description=task["description"], task_type="refactor"
        )
        result = planner.execute(task, ctx)
        subtasks = result.output["subtasks"]
        id_positions = {s["id"]: i for i, s in enumerate(subtasks)}
        for subtask in subtasks:
            for dep_id in subtask.get("dependencies", []):
                assert id_positions[dep_id] < id_positions[subtask["id"]]


# ── Subtask dataclass ───────────────────────────────────────────


class TestSubtaskDataclass:
    def test_subtask_to_dict(self) -> None:
        s = Subtask.simple(id="1", description="test", task_type="edit_file")
        d = s.to_dict()
        assert d["id"] == "1"
        assert d["description"] == "test"
        assert d["dependencies"] == []
