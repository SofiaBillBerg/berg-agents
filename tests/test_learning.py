"""Tests for berg_agents.agents.learning — adaptive learning."""

import pytest

from berg_agents.agents.learning import Learning
from berg_agents.core.interface import TaskComplexity, TaskContext


@pytest.fixture
def learning() -> Learning:
    return Learning()


# ── can_handle ──────────────────────────────────────────────────


class TestCanHandle:
    def test_record_outcome_returns_full_confidence(
        self, learning: Learning
    ) -> None:
        assert (
            learning.can_handle({
                "task_type": "record_outcome",
                "description": "x",
            })
            == 1.0
        )

    def test_analyze_returns_full_confidence(self, learning: Learning) -> None:
        assert (
            learning.can_handle({"task_type": "analyze", "description": "x"})
            == 1.0
        )

    def test_generic_returns_low_confidence(self, learning: Learning) -> None:
        assert (
            learning.can_handle({"task_type": "generic", "description": "x"})
            == 0.1
        )


# ── Execute ─────────────────────────────────────────────────────


class TestExecute:
    def test_execute_returns_success(self, learning: Learning) -> None:
        task = {"description": "record outcome", "task_type": "record_outcome"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="record_outcome",
            metadata={"model_used": "qwen3.5:9b", "success": True},
        )
        result = learning.execute(task, ctx)
        assert result.success is True
        assert result.output["status"] == "recorded"

    def test_learning_generated(self, learning: Learning) -> None:
        task = {"description": "record outcome", "task_type": "record_outcome"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="record_outcome",
            metadata={"model_used": "qwen3.5:9b", "success": True},
        )
        result = learning.execute(task, ctx)
        assert "learning" in result.output
        assert "insight" in result.output["learning"]

    def test_stats_populated(self, learning: Learning) -> None:
        task = {"description": "record outcome", "task_type": "record_outcome"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="record_outcome",
            metadata={"model_used": "qwen3.5:9b", "success": True},
        )
        result = learning.execute(task, ctx)
        assert result.output["stats"]["total"] >= 1


# ── Learning insights ───────────────────────────────────────────


class TestLearningInsights:
    def test_success_generates_reinforce(self, learning: Learning) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="edit_file",
            metadata={
                "model_used": "qwen3.5:9b",
                "success": True,
                "user_corrected": False,
            },
        )
        result = learning.execute(task, ctx)
        assert result.output["learning"]["action"] == "reinforce"

    def test_user_correction_generates_upgrade(
        self, learning: Learning
    ) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="edit_file",
            metadata={
                "model_used": "qwen3.5:9b",
                "success": True,
                "user_corrected": True,
            },
        )
        result = learning.execute(task, ctx)
        assert result.output["learning"]["action"] == "upgrade_model_tier"

    def test_failure_generates_review(self, learning: Learning) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="edit_file",
            metadata={"model_used": "qwen3.5:9b", "success": False},
        )
        result = learning.execute(task, ctx)
        assert result.output["learning"]["action"] == "review_approach"


# ── Learnings tracking ──────────────────────────────────────────


class TestLearningsTracking:
    def test_get_learnings_returns_all(self, learning: Learning) -> None:
        for i in range(3):
            task = {"description": f"task {i}", "task_type": "edit_file"}
            ctx = TaskContext(
                task_id=f"t{i}",
                description=task["description"],
                task_type="edit_file",
                metadata={"model_used": "qwen3.5:9b", "success": True},
            )
            learning.execute(task, ctx)
        assert len(learning.get_learnings()) == 3

    def test_get_best_model(self, learning: Learning) -> None:
        # Record successes for gpt-4o
        for _ in range(5):
            task = {"description": "edit", "task_type": "edit_file"}
            ctx = TaskContext(
                task_id="t1",
                description=task["description"],
                task_type="edit_file",
                metadata={"model_used": "gpt-4o", "success": True},
            )
            learning.execute(task, ctx)
        best = learning.get_best_model_for_task("edit_file")
        assert best == "gpt-4o"

    def test_recommendation_for_low_success(self, learning: Learning) -> None:
        # Record many failures
        for _ in range(5):
            task = {"description": "edit", "task_type": "edit_file"}
            ctx = TaskContext(
                task_id="t1",
                description=task["description"],
                task_type="edit_file",
                metadata={"model_used": "qwen3.5:9b", "success": False},
            )
            learning.execute(task, ctx)
        # Check stats
        stats = learning.router.get_outcome_stats()
        by_task = stats.get("by_task_type", {})
        if "edit_file" in by_task:
            total = (
                by_task["edit_file"]["success"]
                + by_task["edit_file"]["failure"]
            )
            if total >= 3:
                recommendation = learning._generate_recommendation(
                    "edit_file", stats
                )
                assert recommendation is not None
                assert (
                    "upgrade" in recommendation.lower()
                    or "Low" in recommendation
                )
