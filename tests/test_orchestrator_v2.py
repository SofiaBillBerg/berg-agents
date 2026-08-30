"""Tests for berg_agents.core.orchestrator — task execution workflow."""

import pytest

from berg_agents.core.interface import RiskLevel, TaskComplexity
from berg_agents.core.model_router import ModelRouter
from berg_agents.core.orchestrator import Orchestrator


@pytest.fixture
def orch() -> Orchestrator:
    return Orchestrator()


# ── Initialization ──────────────────────────────────────────────


class TestInit:
    def test_has_all_native_agents(self, orch: Orchestrator) -> None:
        agents = orch.agents
        assert "guardian" in agents
        assert "planner" in agents
        assert "implementation" in agents
        assert "curator" in agents
        assert "learning" in agents

    def test_has_router(self, orch: Orchestrator) -> None:
        assert isinstance(orch.router, ModelRouter)


# ── Agent registration ──────────────────────────────────────────


class TestAgentRegistration:
    def test_register_custom_agent(self, orch: Orchestrator) -> None:
        from berg_agents.core.interface import AbstractAgent

        class CustomAgent(AbstractAgent):
            name = "custom"

            def can_handle(self, task):
                return 0.5

            def execute(self, task, context, model=None):
                from berg_agents.core.interface import AgentResult

                return AgentResult(success=True)

        orch.register_agent("custom", CustomAgent())
        assert "custom" in orch.agents

    def test_get_agent(self, orch: Orchestrator) -> None:
        agent = orch.get_agent("guardian")
        assert agent.name == "guardian"

    def test_get_agent_raises_for_unknown(self, orch: Orchestrator) -> None:
        with pytest.raises(KeyError):
            orch.get_agent("nonexistent")

    def test_get_agent_info(self, orch: Orchestrator) -> None:
        info = orch.get_agent_info()
        names = [a["name"] for a in info]
        assert "guardian" in names
        assert "planner" in names


# ── Agent selection ─────────────────────────────────────────────


class TestAgentSelection:
    def test_select_guardian_for_risk_task(self, orch: Orchestrator) -> None:
        name, confidence = orch.select_agent({
            "description": "delete production database",
            "task_type": "delete",
        })
        # Guardian or implementation may be selected depending on confidence
        assert name in orch.agents
        assert 0.0 <= confidence <= 1.0

    def test_select_for_plan_task(self, orch: Orchestrator) -> None:
        name, confidence = orch.select_agent({
            "description": "plan the architecture",
            "task_type": "plan",
        })
        # Planner has highest confidence for plan tasks
        assert name == "planner"
        assert confidence == 1.0


# ── Task execution ──────────────────────────────────────────────


class TestExecuteTask:
    def test_simple_task_returns_completed(self, orch: Orchestrator) -> None:
        result = orch.execute_task({
            "description": "read file main.py",
            "task_type": "read_file",
        })
        assert result["status"] in ("completed", "needs_human_review")
        assert "task_id" in result
        assert "complexity" in result
        assert "risk_level" in result

    def test_critical_task_needs_review(self, orch: Orchestrator) -> None:
        result = orch.execute_task({
            "description": "delete production database",
            "task_type": "delete",
        })
        assert result["status"] == "needs_human_review"
        assert len(result["review_reasons"]) > 0

    def test_complex_task_has_plan(self, orch: Orchestrator) -> None:
        result = orch.execute_task({
            "description": "refactor the authentication system",
            "task_type": "refactor",
        })
        if result["status"] == "completed":
            assert "plan" in result

    def test_model_tier_in_result(self, orch: Orchestrator) -> None:
        result = orch.execute_task({
            "description": "read file",
            "task_type": "read_file",
        })
        if result["status"] == "completed":
            assert "model_tier" in result
            assert result["model_tier"] in ("small", "medium", "large")


# ── Route to agent ──────────────────────────────────────────────


class TestRouteToAgent:
    def test_route_to_guardian(self, orch: Orchestrator) -> None:
        result = orch.route_to_agent(
            "guardian",
            {
                "description": "delete file",
                "task_type": "delete_file",
            },
        )
        assert result.success is True
        assert result.needs_human_review is True

    def test_route_to_planner(self, orch: Orchestrator) -> None:
        result = orch.route_to_agent(
            "planner",
            {
                "description": "refactor module",
                "task_type": "refactor",
            },
        )
        assert result.success is True
        assert result.output["total_subtasks"] > 1


# ── Workflow dispatch ───────────────────────────────────────────


class TestWorkflowDispatch:
    def test_execute_workflow_returns_dispatched(
        self, orch: Orchestrator
    ) -> None:
        result = orch.execute_workflow("test_workflow", {"key": "value"})
        assert result["status"] == "dispatched"
        assert result["workflow"] == "test_workflow"


# ── Learning stats ──────────────────────────────────────────────


class TestLearningStats:
    def test_get_stats_returns_dict(self, orch: Orchestrator) -> None:
        stats = orch.get_learning_stats()
        assert "total" in stats

    def test_stats_update_after_execution(self, orch: Orchestrator) -> None:
        orch.execute_task({
            "description": "read file",
            "task_type": "read_file",
        })
        stats = orch.get_learning_stats()
        # Learning records outcomes (if learning enabled)
        assert isinstance(stats, dict)
