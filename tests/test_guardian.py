"""Tests for berg_agents.agents.guardian — HITL decision agent."""

import pytest

from berg_agents.agents.guardian import Guardian
from berg_agents.core.interface import RiskLevel, TaskComplexity, TaskContext


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def guardian() -> Guardian:
    return Guardian()


# ── Risk Assessment ────────────────────────────────────────────


class TestAssessRisk:
    def test_delete_is_high_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "delete user data",
            "task_type": "delete",
        })
        assert risk == RiskLevel.HIGH

    def test_security_is_high_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "update API key",
            "task_type": "security_change",
        })
        assert risk == RiskLevel.HIGH

    def test_credentials_is_high_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "rotate credentials",
            "task_type": "config",
        })
        assert risk == RiskLevel.HIGH

    def test_production_is_high_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "deploy to production",
            "task_type": "deploy",
        })
        assert risk == RiskLevel.HIGH

    def test_refactor_is_medium_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "refactor module",
            "task_type": "refactor",
        })
        assert risk == RiskLevel.MEDIUM

    def test_install_is_medium_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "install package",
            "task_type": "install_package",
        })
        assert risk == RiskLevel.MEDIUM

    def test_read_is_low_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "read file main.py",
            "task_type": "read_file",
        })
        assert risk == RiskLevel.LOW

    def test_search_is_low_risk(self, guardian: Guardian) -> None:
        risk = guardian.assess_risk({
            "description": "search for patterns",
            "task_type": "search_code",
        })
        assert risk == RiskLevel.LOW


# ── HITL Decision ───────────────────────────────────────────────


class TestNeedsHumanReview:
    def test_critical_always_needs_review(self, guardian: Guardian) -> None:
        task = {"description": "delete database", "task_type": "delete"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.CRITICAL
        )
        assert needs_review is True
        assert any("Critical" in r for r in reasons)

    def test_high_risk_needs_review(self, guardian: Guardian) -> None:
        task = {"description": "deploy to production", "task_type": "deploy"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.STANDARD
        )
        assert needs_review is True
        assert any("High risk" in r for r in reasons)

    def test_low_confidence_needs_review(self, guardian: Guardian) -> None:
        task = {"description": "edit config", "task_type": "edit_file"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.STANDARD, confidence=0.4
        )
        assert needs_review is True
        assert any("confidence" in r.lower() for r in reasons)

    def test_human_leads_type_needs_review(self, guardian: Guardian) -> None:
        task = {"description": "migrate data", "task_type": "production_deploy"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.STANDARD
        )
        assert needs_review is True
        assert any("Human-leads" in r for r in reasons)

    def test_ask_before_type_needs_review(self, guardian: Guardian) -> None:
        task = {"description": "remove file", "task_type": "delete_file"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.STANDARD
        )
        assert needs_review is True
        assert any("Ask-before" in r for r in reasons)

    def test_auto_execute_no_review(self, guardian: Guardian) -> None:
        task = {"description": "read file", "task_type": "read_file"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.TRIVIAL
        )
        assert needs_review is False

    def test_notify_after_no_review(self, guardian: Guardian) -> None:
        task = {"description": "edit file", "task_type": "edit_file"}
        needs_review, reasons = guardian.needs_human_review(
            task, TaskComplexity.STANDARD
        )
        assert needs_review is False


# ── Execute (full agent interface) ──────────────────────────────


class TestExecute:
    def test_execute_returns_agent_result(self, guardian: Guardian) -> None:
        task = {
            "description": "delete production database",
            "task_type": "delete",
        }
        ctx = TaskContext(
            task_id="t1",
            description="delete production database",
            task_type="delete",
            complexity=TaskComplexity.CRITICAL,
        )
        result = guardian.execute(task, ctx)
        assert result.success is True
        assert result.needs_human_review is True
        assert len(result.review_reasons) > 0

    def test_execute_low_risk_no_review(self, guardian: Guardian) -> None:
        task = {"description": "read file main.py", "task_type": "read_file"}
        ctx = TaskContext(
            task_id="t2",
            description="read file main.py",
            task_type="read_file",
            complexity=TaskComplexity.TRIVIAL,
        )
        result = guardian.execute(task, ctx)
        assert result.success is True
        assert result.needs_human_review is False

    def test_execute_output_contains_risk_and_complexity(
        self, guardian: Guardian
    ) -> None:
        task = {
            "description": "refactor module structure",
            "task_type": "refactor",
        }
        ctx = TaskContext(
            task_id="t3",
            description="refactor module structure",
            task_type="refactor",
            complexity=TaskComplexity.COMPLEX,
        )
        result = guardian.execute(task, ctx)
        assert result.output["risk_level"] == "medium"
        assert result.output["complexity"] == "complex"


# ── Agent Info ──────────────────────────────────────────────────


class TestAgentInfo:
    def test_guardian_metadata(self, guardian: Guardian) -> None:
        info = guardian.get_info()
        assert info["name"] == "guardian"
        assert "hitl" in str(info["capabilities"])

    def test_can_handle_always_high(self, guardian: Guardian) -> None:
        confidence = guardian.can_handle({"description": "anything"})
        assert confidence == 0.8


# ── Custom Configuration ────────────────────────────────────────


class TestCustomConfig:
    def test_custom_auto_execute_types(self) -> None:
        g = Guardian(auto_execute=["read_file", "list_files", "custom_type"])
        assert "custom_type" in g.auto_execute

    def test_custom_human_leads_types(self) -> None:
        g = Guardian(human_leads=["my_critical_task"])
        task = {"description": "do it", "task_type": "my_critical_task"}
        needs_review, reasons = g.needs_human_review(
            task, TaskComplexity.STANDARD
        )
        assert needs_review is True
