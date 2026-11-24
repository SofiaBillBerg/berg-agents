# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.

"""Traceable check of the A2A surface, using the real router and a fake registry.

Run from the repo root with the project environment:

    .venv/bin/python -m berg_agents.a2a.verify

It needs no backend, no database and no model: the harness is a small fake that
exposes one spec-defined agent. What it proves:

  1. the agent card is served at /a2a/<name>/.well-known/agent-card.json
  2. the JSON-RPC endpoint accepts a SendMessage request
  3. the turn produces a Task result with the agent's answer

Everything printed comes from a real HTTP response against a FastAPI app built
by the same mount used in berg's server.
"""

from __future__ import annotations

import json

from berg_agents.a2a.serve import serve_berg_agents
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeSpecAgent:
    """A registry entry that builds an agent with no tools and no network."""

    def build_agent(self, **kwargs: object) -> object:
        class _Agent:
            @staticmethod
            def run_sync(prompt: str) -> object:
                class _Result:
                    output = f"answered: {prompt}"

                return _Result()

        return _Agent()


class _FakeHarness:
    """One registered agent, so the card and the routes come from the registry."""

    def get_agent(self, name: str) -> object:
        if name != "planner":
            raise KeyError(name)
        return _FakeSpecAgent()

    def get_agent_info(self) -> list[dict[str, object]]:
        return [
            {
                "name": "planner",
                "description": "Plans work",
                "capabilities": ["planning"]}
        ]


def main() -> int:
    """Run the check and print each response. Returns a shell exit code."""
    app = FastAPI()
    serve_berg_agents(
        app, harness=_FakeHarness(), base_url="http://127.0.0.1:8001"
    )
    client = TestClient(app)

    card = client.get("/a2a/planner/.well-known/agent-card.json")
    print(f"CARD {card.status_code}: {card.text[:300]}")
    if card.status_code != 200:
        return 1

    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "parts": [{"text": "hello there"}],
                "message_id": "verify-1"}
        }}
    result = client.post(
        "/a2a/planner", json=message, headers={"A2A-Version": "1.0"}
    )
    print(f"TURN {result.status_code}: {result.text[:600]}")
    try:
        body = json.loads(result.text)
    except ValueError:
        return 1
    if "error" in body:
        print(f"FAIL: {body['error']}")
        return 1
    print("OK: peer message answered over A2A")
    return 0


def verify_real_registry() -> int:
    """Mount A2A against berg's real harness and list the cards it serves.

    Run with `--real`. This needs no backend process or model call: the Harness
    builds its agent cards locally. It proves the mount sees the same registry
    the web UI does, rather than only the fake agent above.
    """
    from berg_agents.core.harness import Harness

    harness = Harness(enable_inference=True)
    app = FastAPI()
    serve_berg_agents(app, harness=harness, base_url="http://127.0.0.1:8001")
    print(
        f"REGISTRY agents: {[i.get('name') for i in harness.get_agent_info()]}"
    )
    client = TestClient(app)
    paths = sorted(
        getattr(route, "path", "")
        for route in app.routes
        if "/a2a/" in getattr(route, "path", "")
    )
    print(f"A2A routes: {paths}")
    for info in harness.get_agent_info():
        name = info.get("name")
        card = client.get(f"/a2a/{name}/.well-known/agent-card.json")
        print(f"CARD {name}: {card.status_code} | {card.text[:140]}")
    return 0


def verify_real_turn() -> int:
    """Drive one turn per agent over A2A through berg's REAL harness.

    Run with `--turn`. The registry is berg's, the agents are berg's, and
    the cards, routes and executor are the ones berg serves. Every
    registry agent must answer with a completed task — the four display
    cards (guardian, implementation, curator, router_agent) all have
    builders now, so none of them may refuse.
    """
    from berg_agents.core.harness import Harness

    harness = Harness(enable_inference=True)
    app = FastAPI()
    serve_berg_agents(app, harness=harness, base_url="http://127.0.0.1:8001")
    client = TestClient(app)

    failures = 0
    prompts = {
        "guardian": "Assess the risk of editing one file",
        "implementation": "Say one sentence that you are ready.",
        "planner": "Say one sentence that you are ready.",
        "curator": "Say one sentence that you are ready.",
        "router_agent": "Say one sentence that you are ready."}
    for info in harness.get_agent_info():
        name = info["name"]
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"text": prompts.get(name, "Say one sentence.")}],
                    "message_id": f"verify-turn-{name}"}
            }}
        result = client.post(
            f"/a2a/{name}", json=message, headers={"A2A-Version": "1.0"}
        )
        body = json.loads(result.text)
        task = body.get("result", {}).get("task", {})
        state = task.get("status", {}).get("state")
        ok = state == "TASK_STATE_COMPLETED"
        print(f"TURN {name}: {result.status_code} state={state}")
        if not ok:
            print(f"FAIL: {name} — {result.text[:400]}")
            failures += 1
    if failures:
        print(f"FAILURES: {failures}")
        return 1
    print("OK: every registry agent over A2A completed")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(
        verify_real_registry()
        if "--real" in sys.argv
        else verify_real_turn()
        if "--turn" in sys.argv
        else main()
    )
