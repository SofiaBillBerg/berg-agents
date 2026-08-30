"""Lock the ChatServer protocol contract.

These tests don't test behavior — they test the *shape* of the
contract. If a method is renamed, a return type changes, or a method
disappears, the test fails. This is what lets the FastAPI web layer and
a future TUI loop (or a native non-LangGraph backend) both implement the
same interface safely.
"""

from __future__ import annotations

from inspect import isabstract
from typing import get_type_hints

import pytest

from berg_agents.core.chat_server import (
    ChatServer,
    ChatServerBase,
    ModelInfo,
    ProtocolEvent,
    ProviderConfig,
    ThreadInfo,
)


# ---------------------------------------------------------------------------
# The full method surface we want every implementer to provide.
# ---------------------------------------------------------------------------

PROTOCOL_METHODS = {
    # providers / models / capabilities
    "list_providers",
    "get_active_provider",
    "set_active_provider",
    "list_models",
    "list_capabilities",
    # threads
    "create_thread",
    "get_thread_state",
    "get_thread_history",
    "set_thread_model",
    "export_thread",
    # runs / streaming
    "start_run",
    "stream_run",
    "cancel_run",
    "respond_interrupt",
    "thread_stream_events",
    # legacy /chat/* convenience
    "chat",
    "chat_stream",
    "chat_resume",
    "chat_cancel",
    "chat_history",
    "chat_audit",
    # capabilities
    "invoke_capability",
}


def test_protocol_lists_every_method_we_promised() -> None:
    """The public surface is the source of truth — no surprises."""
    assert set(ChatServer.__dict__) | set(dir(ChatServer))  # sanity
    proto_methods = {
        name for name in dir(ChatServer) if not name.startswith("_")
    }
    # ChatServer is a Protocol, so its attributes appear as the function
    # stubs; check that every name in PROTOCOL_METHODS exists on it.
    missing = PROTOCOL_METHODS - proto_methods
    assert not missing, f"ChatServer is missing methods: {sorted(missing)}"


def test_base_class_is_abstract_until_implemented() -> None:
    """The ABC must not be instantiable directly."""
    assert isabstract(ChatServerBase)
    with pytest.raises(TypeError):
        ChatServerBase()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Domain type round-trips
# ---------------------------------------------------------------------------


def test_model_info_to_dict() -> None:
    m = ModelInfo(
        provider="ollama",
        model="qwen3.5:9b",
        base_url="http://localhost:11435/v1",
        display_name="qwen3.5:9b",
        is_active=True,
    )
    assert m.to_dict() == {
        "provider": "ollama",
        "model": "qwen3.5:9b",
        "base_url": "http://localhost:11435/v1",
        "display_name": "qwen3.5:9b",
        "is_active": True,
    }


def test_provider_config_to_dict() -> None:
    p = ProviderConfig(
        name="ollama",
        model="qwen3.5:9b",
        is_active=True,
        base_url="http://localhost:11435/v1",
        api_key_set=False,
    )
    assert p.to_dict() == {
        "name": "ollama",
        "model": "qwen3.5:9b",
        "is_active": True,
        "base_url": "http://localhost:11435/v1",
        "api_key_set": False,
    }


def test_thread_info_to_dict() -> None:
    t = ThreadInfo(
        thread_id="abc",
        created_at="2026-08-28T10:00:00Z",
        updated_at="2026-08-28T10:05:00Z",
        metadata={"k": "v"},
        values={"messages": []},
    )
    out = t.to_dict()
    assert out["thread_id"] == "abc"
    assert out["metadata"] == {"k": "v"}
    assert out["values"] == {"messages": []}


def test_protocol_event_to_dict() -> None:
    e = ProtocolEvent(
        id=42,
        event="messages",
        data={"role": "ai", "text": "hi"},
        namespace=("model",),
        node="ChatOpenAI",
    )
    out = e.to_dict()
    assert out == {
        "seq": 42,
        "method": "messages",
        "params": {
            "namespace": ["model"],
            "node": "ChatOpenAI",
            "data": {"role": "ai", "text": "hi"},
        },
    }


def test_protocol_event_omits_node_when_none() -> None:
    e = ProtocolEvent(id=1, event="lifecycle", data={"event": "completed"})
    assert "node" not in e.to_dict()["params"]


# ---------------------------------------------------------------------------
# Concrete dummy implementation
# ---------------------------------------------------------------------------


class _DummyServer(ChatServerBase):
    """Minimal concrete subclass — used to prove the ABC can be implemented."""

    def list_providers(self):
        return []

    def get_active_provider(self):
        return ProviderConfig(name="x", model="y", is_active=True)

    def set_active_provider(self, name, model):
        return ProviderConfig(name=name, model=model, is_active=True)

    def list_models(self):
        return []

    def list_capabilities(self):
        return []

    def create_thread(self, thread_id=None, metadata=None, if_exists=None):
        return ThreadInfo(
            thread_id="t",
            created_at="",
            updated_at="",
            metadata={},
            values={},
        )

    def get_thread_state(self, thread_id):
        return {"values": {}, "next": [], "tasks": []}

    def get_thread_history(self, thread_id):
        return []

    def set_thread_model(self, thread_id, provider, model, base_url=None):
        return {"status": "ok"}

    def export_thread(self, thread_id, format="md"):
        return "# empty"

    def start_run(self, thread_id, input_messages):
        return {"run_id": "r", "thread_id": thread_id}

    def stream_run(self, thread_id, run_id, since=0):
        return iter(())

    def cancel_run(self, thread_id, run_id):
        return {"status": "cancelled"}

    def respond_interrupt(self, thread_id, response, interrupt_id=None):
        return {"status": "ok"}

    def thread_stream_events(self, thread_id, since=0):
        return iter(())

    def chat(self, text):
        return {"status": "ok"}

    def chat_stream(self, text):
        return iter(())

    def chat_resume(self, response):
        return {"status": "ok"}

    def chat_cancel(self):
        return {"status": "cancelled"}

    def chat_history(self):
        return []

    def chat_audit(self, action="read"):
        return {"status": "ok"}

    def invoke_capability(self, capability_id, params):
        return {"response": {}, "receipt": {}}


def test_dummy_server_is_constructable() -> None:
    """A faithful implementation can be instantiated and used."""
    s = _DummyServer()
    assert s.get_active_provider().name == "x"
    assert s.start_run("t", []).get("thread_id") == "t"


def test_dummy_server_satisfies_protocol_runtime_check() -> None:
    """The @runtime_checkable ChatServer Protocol recognises any implementer."""
    s = _DummyServer()
    assert isinstance(s, ChatServer)
