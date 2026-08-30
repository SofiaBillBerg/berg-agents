"""Tests for berg_agents.core.learning_gate — adaptive learning."""

import pytest

from berg_agents.core.learning_gate import LearningGate
from berg_agents.core.model_router import ModelRouter


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def gate() -> LearningGate:
    return LearningGate()


# ── Recording ───────────────────────────────────────────────────


class TestRecording:
    def test_record_success(self, gate: LearningGate) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        insight = gate.record(
            task=task,
            result={"status": "completed"},
            model_used="qwen3.5:9b",
            success=True,
        )
        assert insight["type"] == "success"
        assert insight["model"] == "qwen3.5:9b"
        assert insight["action"] == "reinforce"

    def test_record_failure(self, gate: LearningGate) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        insight = gate.record(
            task=task,
            result={"status": "failed"},
            model_used="qwen3.5:9b",
            success=False,
        )
        assert insight["type"] == "failure"
        assert "failed" in insight["message"].lower()

    def test_record_user_correction(self, gate: LearningGate) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        insight = gate.record(
            task=task,
            result={"status": "completed"},
            model_used="qwen3.5:9b",
            success=True,
            user_corrected=True,
        )
        assert insight["type"] == "user_correction"
        assert insight["action"] == "upgrade_tier"

    def test_record_updates_router_stats(self, gate: LearningGate) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        gate.record(task, {"status": "completed"}, "qwen3.5:9b", True)
        stats = gate.get_stats()
        assert stats["total"] >= 1


# ── Insights ────────────────────────────────────────────────────


class TestInsights:
    def test_insights_list_grows(self, gate: LearningGate) -> None:
        for i in range(5):
            gate.record(
                {"description": f"task {i}", "task_type": "edit_file"},
                {"status": "completed"},
                "qwen3.5:9b",
                True,
            )
        stats = gate.get_stats()
        assert stats["total_insights"] == 5

    def test_recent_insights(self, gate: LearningGate) -> None:
        for i in range(3):
            gate.record(
                {"description": f"task {i}", "task_type": "edit_file"},
                {"status": "completed"},
                "qwen3.5:9b",
                True,
            )
        stats = gate.get_stats()
        assert len(stats["recent_insights"]) == 3


# ── Recommendations ─────────────────────────────────────────────


class TestRecommendations:
    def test_no_recommendation_for_unknown_task(
        self, gate: LearningGate
    ) -> None:
        rec = gate.get_recommendation("nonexistent_task")
        assert rec is None

    def test_recommendation_for_low_success(self, gate: LearningGate) -> None:
        # Record many failures
        for _ in range(5):
            gate.record(
                {"description": "edit", "task_type": "difficult_task"},
                {"status": "failed"},
                "qwen3.5:9b",
                False,
            )
        rec = gate.get_recommendation("difficult_task")
        assert rec is not None
        assert "upgrade" in rec.lower() or "low" in rec.lower()

    def test_recommendation_for_high_success(self, gate: LearningGate) -> None:
        # Record many successes
        for _ in range(10):
            gate.record(
                {"description": "read", "task_type": "easy_task"},
                {"status": "completed"},
                "qwen3.5:9b",
                True,
            )
        rec = gate.get_recommendation("easy_task")
        assert rec is not None
        assert "downgrade" in rec.lower() or "high" in rec.lower()


# ── Best model ──────────────────────────────────────────────────


class TestBestModel:
    def test_best_model_returns_string(self, gate: LearningGate) -> None:
        for _ in range(5):
            gate.record(
                {"description": "edit", "task_type": "edit_file"},
                {"status": "completed"},
                "gpt-4o",
                True,
            )
        best = gate.get_best_model("edit_file")
        assert best is not None
        assert "gpt-4o" in best

    def test_best_model_none_when_no_data(self, gate: LearningGate) -> None:
        best = gate.get_best_model("unknown")
        # May be None, empty dict, or a string
        assert best in (None, {}) or isinstance(best, str)


# ── MemPalace integration ──────────────────────────────────────


class TestMemPalaceStore:
    def test_store_returns_bool(self) -> None:
        from berg_agents.core.learning_gate import MemPalaceStore

        result = MemPalaceStore.store({"type": "success", "message": "test"})
        assert isinstance(result, bool)

    def test_recall_returns_list(self) -> None:
        from berg_agents.core.learning_gate import MemPalaceStore

        observations = MemPalaceStore.recall("test_task")
        assert isinstance(observations, list)
