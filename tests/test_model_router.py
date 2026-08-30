"""Tests for berg_agents.core.model_router — complexity-based model selection."""

import pytest

from berg_agents.core.interface import TaskComplexity
from berg_agents.core.model_router import ModelRouter


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter()


# ── Complexity Estimation ───────────────────────────────────────


class TestEstimateComplexity:
    def test_trivial_read_file(self, router: ModelRouter) -> None:
        task = {"description": "read file main.py", "task_type": "read_file"}
        assert router.estimate_complexity(task) == TaskComplexity.TRIVIAL

    def test_trivial_list_files(self, router: ModelRouter) -> None:
        task = {"description": "list files in src", "task_type": "list_files"}
        assert router.estimate_complexity(task) == TaskComplexity.TRIVIAL

    def test_trivial_search(self, router: ModelRouter) -> None:
        task = {
            "description": "search for TODO comments",
            "task_type": "search_code",
        }
        assert router.estimate_complexity(task) == TaskComplexity.TRIVIAL

    def test_standard_edit_file(self, router: ModelRouter) -> None:
        task = {"description": "edit file config.py", "task_type": "edit_file"}
        assert router.estimate_complexity(task) == TaskComplexity.STANDARD

    def test_standard_new_file(self, router: ModelRouter) -> None:
        task = {
            "description": "create file for new module",
            "task_type": "new_file",
        }
        assert router.estimate_complexity(task) == TaskComplexity.STANDARD

    def test_complex_refactor(self, router: ModelRouter) -> None:
        task = {
            "description": "refactor authentication system",
            "task_type": "refactor",
        }
        assert router.estimate_complexity(task) == TaskComplexity.COMPLEX

    def test_complex_architecture(self, router: ModelRouter) -> None:
        task = {
            "description": "design new architecture for plugins",
            "task_type": "architecture",
        }
        assert router.estimate_complexity(task) == TaskComplexity.COMPLEX

    def test_critical_delete(self, router: ModelRouter) -> None:
        task = {"description": "delete all user data", "task_type": "delete"}
        assert router.estimate_complexity(task) == TaskComplexity.CRITICAL

    def test_critical_security(self, router: ModelRouter) -> None:
        task = {
            "description": "update security credentials",
            "task_type": "security_change",
        }
        assert router.estimate_complexity(task) == TaskComplexity.CRITICAL

    def test_default_standard_for_unknown(self, router: ModelRouter) -> None:
        task = {"description": "do something mundane", "task_type": "generic"}
        assert router.estimate_complexity(task) == TaskComplexity.STANDARD


# ── Model Selection ─────────────────────────────────────────────


class TestSelectModel:
    def test_trivial_gets_small_tier(self, router: ModelRouter) -> None:
        config = router.select_model(TaskComplexity.TRIVIAL)
        assert config["tier"] == "small"
        assert config["complexity"] == "trivial"
        assert config["human_review_required"] is False

    def test_standard_gets_small_tier(self, router: ModelRouter) -> None:
        config = router.select_model(TaskComplexity.STANDARD)
        assert config["tier"] == "small"
        assert config["human_review_required"] is False

    def test_complex_gets_large_tier(self, router: ModelRouter) -> None:
        config = router.select_model(TaskComplexity.COMPLEX)
        assert config["tier"] == "large"
        assert config["human_review_required"] is False

    def test_critical_gets_large_tier_with_review(
        self, router: ModelRouter
    ) -> None:
        config = router.select_model(TaskComplexity.CRITICAL)
        assert config["tier"] == "large"
        assert config["human_review_required"] is True

    def test_agent_tier_upgrade(self, router: ModelRouter) -> None:
        """Agent preference can upgrade the tier."""
        config = router.select_model(TaskComplexity.TRIVIAL, agent_tier="large")
        assert config["tier"] == "large"

    def test_string_complexity_input(self, router: ModelRouter) -> None:
        config = router.select_model("complex")
        assert config["tier"] == "large"

    def test_models_list_populated(self, router: ModelRouter) -> None:
        config = router.select_model(TaskComplexity.COMPLEX)
        assert len(config["models"]) > 0
        assert isinstance(config["models"], list)


# ── Outcome Recording ───────────────────────────────────────────


class TestOutcomeRecording:
    def test_record_single_outcome(self, router: ModelRouter) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        router.record_outcome(task, model="qwen3.5:9b", success=True)
        stats = router.get_outcome_stats()
        assert stats["total"] == 1
        assert stats["by_task_type"]["edit_file"]["success"] == 1

    def test_record_multiple_outcomes(self, router: ModelRouter) -> None:
        router.record_outcome(
            {"description": "read", "task_type": "read_file"},
            model="qwen3.5:9b",
            success=True,
        )
        router.record_outcome(
            {"description": "edit", "task_type": "edit_file"},
            model="gpt-4o",
            success=False,
            user_corrected=True,
        )
        stats = router.get_outcome_stats()
        assert stats["total"] == 2
        assert stats["by_model"]["qwen3.5:9b"]["success"] == 1
        assert stats["by_model"]["gpt-4o"]["failure"] == 1

    def test_empty_stats(self, router: ModelRouter) -> None:
        stats = router.get_outcome_stats()
        assert stats["total"] == 0
        assert stats["by_task_type"] == {}
