"""Tests for berg_agents.core.interface — AbstractAgent contract."""

from dataclasses import asdict

import pytest

from berg_agents.core.interface import (
    AbstractAgent,
    AgentResult,
    RiskLevel,
    TaskComplexity,
    TaskContext,
)


class ConcreteAgent(AbstractAgent):
    """Minimal concrete implementation for testing."""

    name = "test_agent"
    description = "A test agent"
    preferred_model_tier = "small"
    capabilities = ["read", "write"]

    def can_handle(self, task: dict) -> float:
        return 0.9

    def execute(self, task, context, model=None) -> AgentResult:
        return AgentResult(success=True, output="done")


# ── TaskComplexity ──────────────────────────────────────────────


def test_task_complexity_enum_values() -> None:
    assert TaskComplexity.TRIVIAL.value == "trivial"
    assert TaskComplexity.STANDARD.value == "standard"
    assert TaskComplexity.COMPLEX.value == "complex"
    assert TaskComplexity.CRITICAL.value == "critical"


def test_task_complexity_string_enum() -> None:
    """TaskComplexity is a str enum, so comparison with strings works."""
    assert TaskComplexity.TRIVIAL == "trivial"


# ── RiskLevel ───────────────────────────────────────────────────


def test_risk_level_enum_values() -> None:
    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MEDIUM.value == "medium"
    assert RiskLevel.HIGH.value == "high"
    assert RiskLevel.CRITICAL.value == "critical"


# ── TaskContext ─────────────────────────────────────────────────


def test_task_context_defaults() -> None:
    ctx = TaskContext(task_id="t1", description="do a thing")
    assert ctx.task_id == "t1"
    assert ctx.description == "do a thing"
    assert ctx.task_type == "generic"
    assert ctx.complexity == TaskComplexity.STANDARD
    assert ctx.risk_level == RiskLevel.LOW
    assert ctx.metadata == {}


def test_task_context_to_dict() -> None:
    ctx = TaskContext(
        task_id="t2",
        description="refactor auth",
        task_type="refactor",
        complexity=TaskComplexity.COMPLEX,
        risk_level=RiskLevel.HIGH,
        metadata={"files": ["auth.py"]},
    )
    d = ctx.to_dict()
    assert d["task_id"] == "t2"
    assert d["complexity"] == "complex"
    assert d["risk_level"] == "high"
    assert d["metadata"] == {"files": ["auth.py"]}


# ── AgentResult ─────────────────────────────────────────────────


def test_agent_result_defaults() -> None:
    result = AgentResult(success=True)
    assert result.success is True
    assert result.output is None
    assert result.error is None
    assert result.needs_human_review is False
    assert result.review_reasons == []


def test_agent_result_to_dict() -> None:
    result = AgentResult(
        success=False,
        error="something broke",
        needs_human_review=True,
        review_reasons=["high risk"],
    )
    d = result.to_dict()
    assert d["success"] is False
    assert d["error"] == "something broke"
    assert d["needs_human_review"] is True
    assert d["review_reasons"] == ["high risk"]


# ── AbstractAgent ───────────────────────────────────────────────


def test_abstract_agent_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        AbstractAgent()  # type: ignore[abstract]


def test_concrete_agent_get_info() -> None:
    agent = ConcreteAgent()
    info = agent.get_info()
    assert info["name"] == "test_agent"
    assert info["preferred_model_tier"] == "small"
    assert "read" in info["capabilities"]


def test_concrete_agent_can_handle() -> None:
    agent = ConcreteAgent()
    assert agent.can_handle({"description": "read file"}) == 0.9


def test_concrete_agent_execute() -> None:
    agent = ConcreteAgent()
    ctx = TaskContext(task_id="t1", description="test")
    result = agent.execute({"description": "test"}, ctx)
    assert result.success is True
    assert result.output == "done"
