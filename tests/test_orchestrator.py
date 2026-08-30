"""Tests for the framework-agnostic core Orchestrator."""

from __future__ import annotations

import json

from pathlib import Path

from berg_agents.core.orchestrator import Orchestrator


def _write_registry(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_orchestrator_with_no_plugins_has_empty_registry(
    tmp_path: Path,
) -> None:
    orch = Orchestrator(plugins=[])
    assert orch.registry == {"agents": [], "workflows": []}


def test_orchestrator_loads_from_plugin_directories(tmp_path: Path) -> None:
    plugin_a = tmp_path / "plugin_a"
    plugin_b = tmp_path / "plugin_b"
    plugin_a.mkdir()
    plugin_b.mkdir()
    _write_registry(
        plugin_a / "registry.json",
        {
            "agents": [{"name": "alpha", "file": "alpha.xml"}],
            "workflows": [],
        },
    )
    _write_registry(
        plugin_b / "registry.json",
        {
            "agents": [{"name": "beta", "file": "beta.xml"}],
            "workflows": [{"name": "wf_b", "file": "wf_b.xml"}],
        },
    )

    orch = Orchestrator(plugins=[plugin_a, plugin_b])

    names = sorted(a["name"] for a in orch.registry["agents"])
    assert names == ["alpha", "beta"]
    assert [w["name"] for w in orch.registry["workflows"]] == ["wf_b"]


def test_orchestrator_route_to_agent_found(tmp_path: Path) -> None:
    plugin = tmp_path / "p"
    plugin.mkdir()
    _write_registry(
        plugin / "registry.json",
        {
            "agents": [{"name": "planner"}],
            "workflows": [],
        },
    )
    orch = Orchestrator(plugins=[plugin])
    assert orch.route_to_agent("planner")["name"] == "planner"


def test_orchestrator_route_to_agent_missing_raises_keyerror() -> None:
    orch = Orchestrator(plugins=[])
    import pytest

    with pytest.raises(KeyError):
        orch.route_to_agent("ghost")


def test_orchestrator_execute_workflow_returns_dispatch_dict() -> None:
    orch = Orchestrator(plugins=[])
    result = orch.execute_workflow("anything", {"a": 1})
    assert result["workflow"] == "anything"
    assert result["context"] == {"a": 1}
    assert result["status"] == "dispatched"
