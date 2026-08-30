"""Tests for the OAP-inspired capability layer.

Covers the capability contract (:mod:`berg_agents.capabilities.base`), the
request/response envelopes (:mod:`berg_agents.capabilities.envelope`), the
hash-chained audit log (:mod:`berg_agents.capabilities.audit`), the registry
discovery and dispatch flow (:mod:`berg_agents.capabilities.registry`) and
the LangChain tool adapter (:mod:`berg_agents.capabilities.tool_adapter`).

The adapter depends on ``langchain.tools.BaseTool``; when that package is
not importable a minimal stand-in is injected into ``sys.modules`` first so
the tests run without the real dependency.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import types

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pydantic import BaseModel, ValidationError

from berg_agents.capabilities.audit import AuditLog, Receipt
from berg_agents.capabilities.base import CapabilityBase, RiskClass
from berg_agents.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from berg_agents.capabilities.registry import CapabilityRegistry
from berg_agents.capabilities.tool_adapter import (
    ToolResult,
    tool_to_capability,
)


# ``berg_agents/__init__.py`` also eagerly imports the provider modules,
# which need ``langchain_ollama`` and ``langchain_openai``; stand in for
# them too when they are missing.
for _module_name, _attr in (
    (
        "langchain_ollama",
        "ChatOllama",
    ),  # TODO remove, use langchain directly and init_chat_model
    (
        "langchain_openai",
        "ChatOpenAI",
    ),  # TODO remove, use langchain directly and init_chat_model
):
    try:
        importlib.import_module(_module_name)
    except (ImportError, AttributeError):
        _module = sys.modules.get(_module_name)
        if _module is None:
            _module = types.ModuleType(_module_name)
            sys.modules[_module_name] = _module
        if not hasattr(_module, _attr):
            setattr(_module, _attr, type(_attr, (), {}))


# ---------------------------------------------------------------------------
# Dummy contracts and capabilities (no network required)
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    """Input contract for the echo test capability."""

    text: str
    times: int = 1


class EchoOutput(BaseModel):
    """Output contract for the echo test capability."""

    text: str


class EchoCapability(CapabilityBase):
    """Low-risk test capability that echoes its input text."""

    id = "echo"
    intent = "Echo the input text a number of times"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:  # ruff: ignore[no-self-use]
        """Execute the echo command.

        :param params: The parsed and validated input parameters.
        :return: The echo output.
        :raises RuntimeError: Always.
        """
        echo_input = EchoInput.model_validate(params)
        return EchoOutput(text=echo_input.text * echo_input.times)


class UpperEchoCapability(CapabilityBase):
    """Second capability sharing the ``echo`` id, used by the replacement test.

    This replaces the ``echo`` capability registered in the fixture.

    Note that this class is defined at module level so it can be pickled
    by the multiprocessing layer in the agent.

    Attributes:
        id: The capability identifier.
        intent: What the capability does.
        input_model: The Pydantic model for the input parameters.
        output_model: The Pydantic model for the output parameters.
        risk_class: The risk class for the capability.
    Methods:
        _execute: The implementation of the capability.

    :param params: The parsed and validated input parameters.
    :return:        The echo output.
    :raise: RuntimeError: Always.
    """

    id = "echo"
    intent = "Echo the input text uppercased"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:  # ruff: ignore[no-self-use]
        """Execute the echo command.

        :param params: The parsed and validated input parameters.
        :return: The echo output.
        :raises RuntimeError: Always.
        """
        echo_input = EchoInput.model_validate(params)
        return EchoOutput(text=echo_input.text.upper() * echo_input.times)


class FailingCapability(CapabilityBase):
    """Test capability whose execution always raises.

    Attributes:
        id: The capability identifier.
        intent: What the capability does.
        input_model: The Pydantic model for the input parameters.
        output_model: The Pydantic model for the output parameters.
    Methods:
        _execute: The implementation of the capability.
    Args:
        params: The parsed and validated input parameters.
    Returns:
        The echo output.
    Raises:
        RuntimeError: Always.
    """

    id = "boom"
    intent = "Always fails"
    input_model = EchoInput
    output_model = EchoOutput

    def _execute(self, params: BaseModel) -> BaseModel:  # ruff: ignore[no-self-use]
        """Execute the echo command.

        :param params: The parsed and validated input parameters.
        :return: The echo output.
        :raises RuntimeError: Always.
        """
        raise RuntimeError("kaboom")


class GatedCapability(CapabilityBase):
    """High-risk test capability that must never run unapproved.

    Attributes:
        id: The capability identifier.
        intent: What the capability does.
        input_model: The Pydantic model for the input parameters.
        output_model: The Pydantic model for the output parameters.
        risk_class: The risk class for the capability.
        executed: A flag to track whether the capability was executed.
    Methods:
        _execute: The implementation of the capability.
    Args:
        params: The parsed and validated input parameters.
    Returns:
        The echo output.
    """

    id = "gated"
    intent = "Dangerous operation"
    input_model = EchoInput
    output_model = EchoOutput
    risk_class = RiskClass.HIGH

    executed = False

    def _execute(self, params: BaseModel) -> BaseModel:
        """Execute the gated command.

        :param params: The parsed and validated input parameters.
        :return: The echo output.
        """
        type(self).executed = True
        return EchoOutput(text="ran")


@pytest.fixture
def registry() -> CapabilityRegistry:
    """Return a fresh registry with a low-risk echo capability registered.

    :returns: The registry instance.
    :rtype: CapabilityRegistry
    """
    reg = CapabilityRegistry()
    # pyrefly: ignore [bad-argument-type]
    reg.register(EchoCapability())  # ty: ignore[invalid-argument-type]
    return reg


# ---------------------------------------------------------------------------
# Capability base contract
# ---------------------------------------------------------------------------


def test_capability_base_rejects_wrong_params_type() -> None:
    """``invoke`` must raise TypeError when params are not the input model.

    :param params: The input parameters.
    :type params: dict
    :raises TypeError: When params are not the expected type.
    :raises ValidationError: When params do not match the input model.
    """
    capability = EchoCapability()
    with pytest.raises(TypeError, match="EchoInput"):
        # pyrefly: ignore [bad-argument-type]
        capability.invoke({"text": "nope"})  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# Envelope construction and validation
# ---------------------------------------------------------------------------


def test_invocation_request_requires_ids() -> None:
    """Missing request_id/capability_id must fail validation.

    :param request_id: The request identifier.
    :type request_id: str
    :param capability_id: The capability identifier.
    :type capability_id: str
    :raises ValidationError: When either field is missing.
    """
    with pytest.raises(ValidationError):
        # pyrefly: ignore [missing-argument]
        InvocationRequest()  # ty: ignore[missing-argument]


def test_invocation_request_defaults() -> None:
    """params/caller default and created_at is an ISO timestamp.

    :returns: The invocation request.
    :rtype: InvocationRequest
    :raises ValidationError: When either field is missing.
    """
    request = InvocationRequest(request_id="r1", capability_id="echo")
    assert request.params == {}
    assert request.caller is None
    assert "T" in request.created_at


def test_invocation_request_accepts_caller_and_params() -> None:
    """Custom caller and params are preserved.

    :returns: The invocation request.
    :rtype: InvocationRequest
    :raises ValidationError: When either field is missing.
    """
    request = InvocationRequest(
        request_id="r1",
        capability_id="echo",
        params={"text": "hi"},
        caller="test",
    )
    assert request.caller == "test"
    assert request.params == {"text": "hi"}


def test_invocation_response_defaults() -> None:
    """Response defaults to an empty ok envelope.

    :return: The invocation response.
    :rtype: InvocationResponse
    :raises ValidationError: When status is not ok or error.
    :raises TypeError: When status is not a string.
    """
    response = InvocationResponse(request_id="r1", capability_id="echo")
    assert response.status == "ok"
    assert response.result is None
    assert response.error is None
    assert response.duration_ms == 0


def test_invocation_response_rejects_invalid_status() -> None:
    """``status`` is restricted to ok/error.

    :return: The invocation response.
    :rtype: InvocationResponse
    :raises ValidationError: When status is not ok or error.
    """
    with pytest.raises(ValidationError):
        InvocationResponse(
            request_id="r1",
            capability_id="echo",
            # pyrefly: ignore [bad-argument-type]
            status="maybe",  # ty: ignore[invalid-argument-type]
        )


# ---------------------------------------------------------------------------
# Registry: discovery
# ---------------------------------------------------------------------------


def test_register_and_discover_returns_metadata(
    registry: CapabilityRegistry,
) -> None:
    """Discover must return metadata for every registered capability.

    :param registry: The capability registry.
    :returns: The metadata for the registered capability.
    :rtype: list[dict[str, Any]]
    """
    metadata = registry.discover()
    assert [entry["id"] for entry in metadata] == ["echo"]
    entry = metadata[0]
    assert entry["intent"] == EchoCapability.intent
    assert entry["risk_class"] == RiskClass.LOW
    assert "input_schema" in entry
    assert "text" in entry["input_schema"]["properties"]


def test_register_replaces_existing_capability(
    registry: CapabilityRegistry,
) -> None:
    """Re-registering the same id must replace the previous entry.

    :param registry: The capability registry.
    :return: The capability registry.
    :rtype: CapabilityRegistry
    :raises AssertionError: If the capability is not replaced.
    :raises ValidationError: If the capability is not replaced.
    :raises TypeError: If the capability is not replaced.
    """
    # pyrefly: ignore [bad-argument-type]
    registry.register(UpperEchoCapability())  # ty: ignore[invalid-argument-type]
    assert len(registry.discover()) == 1
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "hi"}
        )
    )
    assert response.status == "ok"
    assert response.result == {"text": "HI"}


# ---------------------------------------------------------------------------
# Registry: dispatch
# ---------------------------------------------------------------------------


def test_dispatch_valid_params_returns_ok(
    registry: CapabilityRegistry,
) -> None:
    """A valid request dispatches to the capability and returns a result.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the response is not ok.
    """
    response, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1",
            capability_id="echo",
            params={"text": "ha", "times": 2},
        )
    )
    assert response.status == "ok"
    assert response.result == {"text": "haha"}
    assert response.request_id == "r1"
    assert response.capability_id == "echo"
    assert receipt.request_id == "r1"


def test_dispatch_invalid_params_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """Invalid params must produce an error response, not an exception.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the response is not an error.
    """
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"times": "x"}
        )
    )
    assert response.status == "error"
    assert response.error is not None
    assert "invalid params" in response.error


def test_dispatch_unknown_capability_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """An unknown capability id must produce an error response.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the response is not an error.
    """
    response, _ = registry.dispatch(
        InvocationRequest(request_id="r1", capability_id="nope")
    )
    assert response.status == "error"
    assert "unknown capability" in (response.error or "")


def test_dispatch_high_risk_gated_without_approval(
    registry: CapabilityRegistry,
) -> None:
    """High-risk capabilities must be gated until explicitly approved.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the response is not an error.
    """
    GatedCapability.executed = False
    # pyrefly: ignore [bad-argument-type]
    registry.register(GatedCapability())  # ty: ignore[invalid-argument-type]
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="gated", params={"text": "x"}
        )
    )
    assert response.status == "error"
    assert "high-risk" in (response.error or "")
    assert GatedCapability.executed is False


def test_dispatch_invocation_exception_returns_error_response(
    registry: CapabilityRegistry,
) -> None:
    """An exception inside the capability surfaces as an error response.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the response is not an error.
    :raises RuntimeError: When the test capability raises an exception.
    """
    # pyrefly: ignore [bad-argument-type]
    registry.register(FailingCapability())  # ty: ignore[invalid-argument-type]
    response, _ = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="boom", params={"text": "x"}
        )
    )
    assert response.status == "error"
    assert "invocation failed" in (response.error or "")


# ---------------------------------------------------------------------------
# Registry: audit receipts
# ---------------------------------------------------------------------------


def test_dispatch_records_audit_receipt(registry: CapabilityRegistry) -> None:
    """Every dispatch must emit an audit receipt.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the receipt is not properly formed.
    """
    _, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "hi"}
        )
    )
    assert isinstance(receipt, Receipt)
    assert receipt.status == "ok"
    assert receipt.capability_id == "echo"


def test_dispatch_receipts_are_hash_chained(
    registry: CapabilityRegistry,
) -> None:
    """Receipts must link via prev_hash to the previous receipt.

    :param registry: The capability registry.
    :return: The invocation response and audit receipt.
    :rtype: tuple[InvocationResponse, Receipt]
    :raises ValidationError: When the request is invalid.
    :raises TypeError: When the request is invalid.
    :raises AssertionError: If the receipt is not properly formed.

    """
    _, first = registry.dispatch(
        InvocationRequest(
            request_id="r1", capability_id="echo", params={"text": "a"}
        )
    )
    _, second = registry.dispatch(
        InvocationRequest(
            request_id="r2", capability_id="echo", params={"text": "b"}
        )
    )
    assert first.prev_hash == "GENESIS"
    assert second.prev_hash == first.receipt_hash


# ---------------------------------------------------------------------------
# Audit log: hash chaining and append-only behavior
# ---------------------------------------------------------------------------


def test_audit_first_receipt_prev_hash_is_genesis() -> None:
    """The first receipt anchors the chain at GENESIS.

    :return: The audit receipt.
    :rtype: Receipt
    :raises AssertionError: If the receipt is not properly formed.
    :raises ValidationError: When the receipt is not properly formed.
    :raises TypeError: When the receipt is not properly formed.
    """
    log = AuditLog()
    receipt = log.record("r1", "echo", "ok")
    assert receipt.prev_hash == "GENESIS"
    assert receipt.receipt_hash != "GENESIS"


def test_audit_receipts_form_hash_chain() -> None:
    """Each receipt's prev_hash must equal the previous receipt_hash.

    :return: The audit receipt.
    :rtype: Receipt
    :raises AssertionError: If the receipt is not properly formed.
    :raises ValidationError: When the receipt is not properly formed.
    :raises TypeError: When the receipt is not properly formed.
    """
    log = AuditLog()
    receipts = [log.record(f"r{i}", "echo", "ok") for i in range(3)]
    assert receipts[1].prev_hash == receipts[0].receipt_hash
    assert receipts[2].prev_hash == receipts[1].receipt_hash
    assert log.last_hash == receipts[2].receipt_hash


def test_audit_hash_chain_detects_tampering() -> None:
    """Altering any recorded field must break the stored chain hash.

    :raises AssertionError: If the receipt is not properly formed.
    :raises ValidationError: When the receipt is not properly formed.
    :raises TypeError: When the receipt is not properly formed.
    :raises ValueError: If the hash chain is not properly formed.
    :raises KeyError: If the hash chain is not properly formed.
    """
    log = AuditLog()
    first = log.record("r1", "echo", "ok")
    second = log.record("r2", "echo", "ok")

    def chain_hash(prev: str, receipt: Receipt) -> str:
        """Recompute the hash for a receipt.

        :param prev: The previous receipt hash.
        :param receipt: The receipt to hash.
        :return: The computed hash for the receipt.
        :rtype: str
        :raises ValidationError: When the receipt is not properly formed.
        :raises TypeError: When the receipt is not properly formed.
        :raises AssertionError: If the receipt is not properly formed.
        :raises ValueError: If the hash chain is not properly formed.
        """
        parts = [
            prev,
            receipt.request_id,
            receipt.capability_id,
            receipt.status,
            receipt.timestamp,
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    assert chain_hash(first.receipt_hash, second) == second.receipt_hash
    tampered = second.model_copy(update={"request_id": "r2-CHANGED"})
    assert chain_hash(first.receipt_hash, tampered) != second.receipt_hash


def test_audit_read_chain_returns_copy() -> None:
    """read_chain must expose a copy, keeping the log append-only.

    :return: The audit receipt.
    :rtype: Receipt
    :raises AssertionError: If the receipt is not properly formed.
    :raises ValidationError: When the receipt is not properly formed.
    :raises TypeError: When the receipt is not properly formed.
    """
    log = AuditLog()
    log.record("r1", "echo", "ok")
    chain = log.read_chain()
    chain.append(
        Receipt(
            request_id="fake",
            capability_id="echo",
            status="ok",
            timestamp="t",
            prev_hash="x",
            receipt_hash="y",
        )
    )
    assert len(log.read_chain()) == 1


def test_audit_persists_receipts_to_file(tmp_path: Path) -> None:
    """Receipts must be appended as JSON lines when a path is given.

    :param tmp_path: A temporary directory for the test file.
    :type tmp_path: Path
    :raises AssertionError: If the file does not contain the expected data.
    :raises ValidationError: When the receipt is not properly formed.
    :raises TypeError: When the receipt is not properly formed.
    """
    audit_path = tmp_path / "audit.jsonl"
    log = AuditLog(path=audit_path)
    log.record("r1", "echo", "ok")
    log.record("r2", "echo", "error")
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"request_id": "r1"' in lines[0]


# ---------------------------------------------------------------------------
# Tool adapter: wrapping a BaseTool into a Capability
# ---------------------------------------------------------------------------


def _make_tool(
    name: str = "read_file",
    description: str = "Read a file",
    args_schema: type[BaseModel] | None = EchoInput,
    run: Any = None,
) -> MagicMock:
    """Build a mocked LangChain tool for the adapter tests.

    :param name: The tool name.
    :param description: The tool description.
    :param args_schema: The tool's input schema.
    :param run: The tool's run implementation.
    :return: A mocked LangChain tool.
    :rtype: MagicMock
    :raises AssertionError: If the tool is not properly formed.
    :raises ValidationError: When the tool is not properly formed.
    """
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.args_schema = args_schema
    if run is not None:
        tool._run.side_effect = run
    return tool


def test_tool_to_capability_kebab_case_id() -> None:
    """The capability id must be the kebab-cased tool name.

    :param name: The tool name.
    :return: The capability id.
    :rtype: str
    :raises AssertionError: If the id is not kebab-cased.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(_make_tool(name="read_file"))
    assert capability.id == "read-file"


def test_tool_to_capability_intent_from_description() -> None:
    """The intent must come from the tool description.

    :return: The capability intent.
    :rtype: str
    :raises AssertionError: If the intent is not properly extracted.
    :raises KeyError: If the tool description is not properly formed.
    :raises ValidationError: When the tool is not properly formed.
    """
    capability = tool_to_capability(_make_tool(description="Fetch a file"))
    assert capability.intent == "Fetch a file"


def test_tool_to_capability_infers_low_risk_for_read_only_tool() -> None:
    """Read-only tool names map to low risk.

    :raises AssertionError: If the risk class is not low.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(_make_tool(name="search_files"))
    assert capability.risk_class == RiskClass.LOW


def test_tool_to_capability_infers_medium_risk_for_mutating_tool() -> None:
    """Non-read-only tool names map to medium risk.

    :raises AssertionError: If the risk class is not medium.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(_make_tool(name="write_file"))
    assert capability.risk_class == RiskClass.MEDIUM


def test_tool_to_capability_infers_high_risk_for_sensitive_mcp_tool() -> None:
    """Tools from sensitive MCP servers map to high risk.

    :raises AssertionError: If the risk class is not high.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(_make_tool(name="mcp_github__create_issue"))
    assert capability.risk_class == RiskClass.HIGH


def test_tool_to_capability_infers_low_risk_for_readonly_mcp_tool() -> None:
    """Tools from read-only MCP servers map to low risk.

    :raises AssertionError: If the risk class is not low.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(_make_tool(name="mcp_codegraph__explore"))
    assert capability.risk_class == RiskClass.LOW


def test_tool_to_capability_explicit_risk_class_override() -> None:
    """An explicit risk_class must win over the heuristic.

    :return: The capability risk class.
    :rtype: RiskClass
    :raises AssertionError: If the risk class is not high.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    capability = tool_to_capability(
        _make_tool(name="read_file"), risk_class=RiskClass.HIGH
    )
    assert capability.risk_class == RiskClass.HIGH


def test_tool_to_capability_delegates_to_run() -> None:
    """Invoke must call the tool's _run with validated keyword params.

    :raises AssertionError: If the tool was not called with the expected args.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    """
    calls: list[dict[str, Any]] = []

    def run(**kwargs: Any) -> str:
        """Capture the call args.

        :param kwargs: The tool arguments.
        :return: A fake file content.
        :rtype: str
        :raises AssertionError: If the args are not properly passed.
        :raises ValidationError: When the args are not properly formed.
        :raises KeyError: If the args are not properly formed.
        :raises TypeError: When the args are not properly formed.
        :raises ValueError: If the args are not properly formed.
        """
        calls.append(kwargs)
        return "content"

    capability = tool_to_capability(_make_tool(run=run))
    result = capability.invoke(EchoInput(text="hello", times=2))
    assert calls == [{"text": "hello", "times": 2}]
    assert isinstance(result, ToolResult)
    assert result.output == "content"


def test_tool_to_capability_falls_back_to_invoke() -> None:
    """Tools without _run must fall back to invoke(tool_input).

    :raises AssertionError: If the tool was not called with the expected args.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    :raises ValueError: If the args are not properly formed.
    """
    tool = _make_tool()
    tool._run.side_effect = NotImplementedError
    tool.invoke.return_value = "fallback output"
    capability = tool_to_capability(tool)
    result = capability.invoke(EchoInput(text="hello"))
    assert isinstance(result, ToolResult)
    assert result.output == "fallback output"
    tool.invoke.assert_called_once_with({"text": "hello", "times": 1})


def test_tool_to_capability_dispatchable_through_registry() -> None:
    """An adapted tool must work end-to-end through the registry.

    :raises AssertionError: If the tool was not called with the expected args.
    :raises ValidationError: When the tool is not properly formed.
    :raises TypeError: When the tool is not properly formed.
    :raises KeyError: If the tool name is not properly formed.
    :raises ValueError: If the args are not properly formed.
    :raises AssertionError: If the tool was not called with the expected args.
    """
    tool = _make_tool(name="read_file", run=lambda **kwargs: kwargs["text"])
    registry = CapabilityRegistry()
    # pyrefly: ignore [bad-argument-type]
    registry.register(tool_to_capability(tool))  # ty: ignore[invalid-argument-type]
    response, receipt = registry.dispatch(
        InvocationRequest(
            request_id="r1",
            capability_id="read-file",
            params={"text": "hello"},
        )
    )
    assert response.status == "ok"
    assert response.result == {"output": "hello"}
    assert receipt.status == "ok"
