"""Tests for berg_agents.agents.curator — documentation and memory."""

import pytest

from berg_agents.agents.curator import Curator
from berg_agents.core.interface import TaskComplexity, TaskContext


@pytest.fixture
def curator() -> Curator:
    return Curator()


# ── can_handle ──────────────────────────────────────────────────


class TestCanHandle:
    def test_update_docs_returns_full_confidence(
        self, curator: Curator
    ) -> None:
        assert (
            curator.can_handle({"task_type": "update_docs", "description": "x"})
            == 1.0
        )

    def test_document_returns_full_confidence(self, curator: Curator) -> None:
        assert (
            curator.can_handle({"task_type": "document", "description": "x"})
            == 1.0
        )

    def test_generic_returns_low_confidence(self, curator: Curator) -> None:
        assert (
            curator.can_handle({"task_type": "generic", "description": "x"})
            == 0.1
        )

    def test_description_with_keyword(self, curator: Curator) -> None:
        confidence = curator.can_handle({
            "task_type": "generic",
            "description": "update readme with new info",
        })
        assert confidence >= 0.7


# ── Execute ─────────────────────────────────────────────────────


class TestExecute:
    def test_execute_returns_success(self, curator: Curator) -> None:
        task = {
            "description": "update documentation",
            "task_type": "update_docs",
        }
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="update_docs",
        )
        result = curator.execute(task, ctx)
        assert result.success is True
        assert result.output["status"] == "curated"

    def test_actions_populated(self, curator: Curator) -> None:
        task = {"description": "update docs", "task_type": "update_docs"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="update_docs",
        )
        result = curator.execute(task, ctx)
        assert "actions" in result.output

    def test_update_plan_populated(self, curator: Curator) -> None:
        task = {"description": "update docs", "task_type": "update_docs"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="update_docs",
        )
        result = curator.execute(task, ctx)
        assert "update_plan" in result.output


# ── Action determination ────────────────────────────────────────


class TestActionDetermination:
    def test_files_changed_generates_doc_actions(
        self, curator: Curator
    ) -> None:
        task = {"description": "update docs", "task_type": "update_docs"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="update_docs",
            metadata={"files_changed": ["src/auth.py", "src/main.py"]},
        )
        result = curator.execute(task, ctx)
        actions = result.output["actions"]
        assert len(actions) >= 2
        assert all(a["type"] == "code_documentation" for a in actions)

    def test_patterns_generates_pattern_actions(self, curator: Curator) -> None:
        task = {"description": "record patterns", "task_type": "distill"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="distill",
            metadata={"patterns": ["use dataclasses for config"]},
        )
        result = curator.execute(task, ctx)
        actions = result.output["actions"]
        assert any(a["type"] == "pattern" for a in actions)

    def test_decisions_generates_decision_actions(
        self, curator: Curator
    ) -> None:
        task = {"description": "record decision", "task_type": "curate"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="curate",
            metadata={"decisions": ["Use pydantic for validation"]},
        )
        result = curator.execute(task, ctx)
        actions = result.output["actions"]
        assert any(a["type"] == "decision" for a in actions)

    def test_complex_task_generates_default_action(
        self, curator: Curator
    ) -> None:
        task = {"description": "refactor module", "task_type": "refactor"}
        ctx = TaskContext(
            task_id="t1",
            description=task["description"],
            task_type="refactor",
            complexity=TaskComplexity.COMPLEX,
        )
        result = curator.execute(task, ctx)
        actions = result.output["actions"]
        assert len(actions) >= 1
        assert actions[0]["type"] == "knowledge_update"
