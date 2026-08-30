"""Tests for CodeAgents (DeepAgents) skills/memory/todos/summarization wiring.

Covers the workspace-virtual path translation helper and the new
``build_berg_agents`` parameters (``skills``, ``memory``, ``todos_enabled``,
``summarization_trigger``, ``summarization_keep``) including the settings
fallback and middleware assembly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from deepagents.middleware import SummarizationMiddleware
from langchain.chat_models import BaseChatModel

from berg_agents.agents.codeagent import (
    _normalize_context_size,  # ruff: ignore[import-private-name] - testing private helper
)
from berg_agents.agents.codeagent import (
    _resolve_workspace_paths,  # ruff: ignore[import-private-name] - testing private helper
)
from berg_agents.agents.codeagent import build_berg_agents
from berg_agents.config.settings import Settings


def test_resolve_workspace_paths_translation(tmp_path: Path) -> None:
    """Paths are translated to workspace-virtual form.

    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If translation is wrong.
    """
    root = tmp_path
    (root / "skills").mkdir()
    (root / "skills" / "code-conventions").mkdir()

    result = _resolve_workspace_paths(
        [
            "skills/code-conventions",  # relative -> re-rooted
            str(root / "skills" / "code-conventions"),  # absolute under root
            "/workspace/skills/x",  # already virtual -> unchanged
            ("/workspace/skills/labeled", "My Label"),  # tuple keeps label
        ],
        root,
    )

    assert result == [
        "/workspace/skills/code-conventions",
        "/workspace/skills/code-conventions",
        "/workspace/skills/x",
        ("/workspace/skills/labeled", "My Label"),
    ]


def test_resolve_workspace_paths_rejects_outside(tmp_path: Path) -> None:
    """Paths outside the workspace are rejected with ValueError.

    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If an invalid path is accepted.
    """
    with pytest.raises(ValueError, match="outside the workspace"):
        _resolve_workspace_paths(["/etc/passwd"], tmp_path)
    with pytest.raises(ValueError, match="escapes the workspace"):
        _resolve_workspace_paths(["../escape"], tmp_path)


def test_normalize_context_size() -> None:
    """JSON list forms are normalized to middleware-accepted tuples.

    :raises AssertionError: If normalization is wrong.
    """
    assert _normalize_context_size(["messages", 50]) == ("messages", 50)
    assert _normalize_context_size([["messages", 100], ["fraction", 0.9]]) == [
        ("messages", 100),
        ("fraction", 0.9),
    ]
    assert _normalize_context_size({"tokens": 4000, "messages": 10}) == {
        "tokens": 4000,
        "messages": 10,
    }
    assert _normalize_context_size(None) is None


def _build_with(
    monkeypatch: Any,
    *,
    settings: Settings | None = None,
    **build_kwargs: Any,
) -> dict[str, Any]:
    """Run build_berg_agents with isolated registration and capture kwargs.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param settings: Settings instance to return from get_settings.
    :param build_kwargs: Keyword arguments for build_berg_agents.
    :return: The kwargs captured by the fake create_deep_agent.
    """
    from berg_agents.agents import codeagent

    captured: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> str:
        """Capture the create call and return a sentinel.

        :param kwargs: Arguments forwarded to create_deep_agent.
        :return: A sentinel graph marker.
        """
        captured.update(kwargs)
        return "GRAPH"

    monkeypatch.setattr(
        codeagent,
        "register_profiles_from_config_file",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        codeagent,
        "register_profiles_from_settings",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(codeagent, "create_deep_agent", fake_create)
    if settings is not None:
        monkeypatch.setattr(codeagent, "get_settings", lambda: settings)

    fake_llm = MagicMock(spec=BaseChatModel)
    build_berg_agents(fake_llm, **build_kwargs)
    return captured


def test_build_berg_agents_forwards_skills_memory(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Explicit skills/memory are translated and forwarded to create_deep_agent.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If skills/memory are not forwarded.
    """
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "code-conventions").mkdir()
    (tmp_path / "AGENTS.md").write_text("# rules\n", encoding="utf-8")

    captured = _build_with(
        monkeypatch,
        root_dir=tmp_path,
        skills=["skills/code-conventions"],
        memory=["AGENTS.md"],
    )

    assert captured["skills"] == ["/workspace/skills/code-conventions"]
    assert captured["memory"] == ["/workspace/AGENTS.md"]


def test_build_berg_agents_settings_fallback(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """Settings provide skills/memory/todos/summarization defaults.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If settings defaults are not applied.
    """
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "code-conventions").mkdir()
    (tmp_path / "AGENTS.md").write_text("# rules\n", encoding="utf-8")

    settings = Settings(
        skills=["skills/code-conventions"],
        memory=["AGENTS.md"],
        todos_enabled=False,
        summarization_trigger=["messages", 50],
        summarization_keep=["messages", 20],
    )
    captured = _build_with(monkeypatch, settings=settings, root_dir=tmp_path)

    assert captured["skills"] == ["/workspace/skills/code-conventions"]
    assert captured["memory"] == ["/workspace/AGENTS.md"]
    # todos_enabled=False -> no TodoListMiddleware in the assembled stack.
    middleware = captured["middleware"]
    assert not any(m.name == "TodoListMiddleware" for m in middleware)
    # Explicit trigger -> configured SummarizationMiddleware replaces built-in.
    sm = next(m for m in middleware if m.name == "SummarizationMiddleware")
    assert sm._lc_helper.trigger == ("messages", 50)
    assert sm._lc_helper.keep == ("messages", 20)


def test_build_berg_agents_todos_middleware(monkeypatch: Any) -> None:
    """todos_enabled controls TodoListMiddleware presence.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If the middleware is not added/omitted correctly.
    """
    captured = _build_with(monkeypatch, todos_enabled=True)
    assert any(m.name == "TodoListMiddleware" for m in captured["middleware"])

    captured = _build_with(monkeypatch, todos_enabled=False)
    assert not any(
        m.name == "TodoListMiddleware" for m in captured.get("middleware", ())
    )


def test_build_berg_agents_summarization_middleware(monkeypatch: Any) -> None:
    """Explicit trigger adds a configured SummarizationMiddleware.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :raises AssertionError: If the middleware is not added correctly.
    """
    captured = _build_with(
        monkeypatch,
        summarization_trigger=("messages", 50),
        summarization_keep=("messages", 20),
    )
    sm = next(
        m for m in captured["middleware"] if m.name == "SummarizationMiddleware"
    )
    assert sm._lc_helper.trigger == ("messages", 50)
    assert sm._lc_helper.keep == ("messages", 20)

    # No trigger with explicit empty settings -> no SummarizationMiddleware added
    # (harness built-in applies). Must pass empty settings to avoid the
    # default bergagents.jsonc summarization_trigger=["messages", 100].
    captured = _build_with(
        monkeypatch,
        settings=Settings(
            summarization_trigger=None,
            summarization_keep=None,
            todos_enabled=True,
        ),
    )
    assert not any(
        m.name == "SummarizationMiddleware" for m in captured["middleware"]
    )


def test_build_berg_agents_explicit_middleware_not_duplicated(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """A caller-supplied SummarizationMiddleware is not duplicated.

    :param monkeypatch: The pytest-mock monkeypatch fixture.
    :param tmp_path: The pytest temporary directory fixture.
    :raises AssertionError: If the middleware is duplicated.
    """
    from unittest.mock import MagicMock as _Mock

    fake_llm = _Mock(spec=BaseChatModel)
    custom = SummarizationMiddleware(
        model=fake_llm,
        backend=MagicMock(),
        trigger=("messages", 10),
        keep=("messages", 5),
    )
    captured = _build_with(
        monkeypatch,
        summarization_trigger=("messages", 50),
        middleware=[custom],
    )
    matches = [
        m for m in captured["middleware"] if m.name == "SummarizationMiddleware"
    ]
    assert len(matches) == 1
    assert matches[0] is custom
