"""Tests for the Berg Agents UI layer (``berg_agents.ui``).

Covers the rich terminal renderer (:mod:`berg_agents.ui.cli_ui`) and the
FastAPI web UI (:mod:`berg_agents.ui.web`).

The renderer tests build a small in-memory :class:`CapabilityRegistry` with
dummy capabilities so no network or real LLM provider is required. The web
test monkey patches ``get_registry`` to return the same kind of isolated
registry, keeping the suite hermetic and fast.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import io

from berg_agents.capabilities.audit import Receipt
from berg_agents.capabilities.base import CapabilityBase, RiskClass
from berg_agents.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from berg_agents.capabilities.registry import CapabilityRegistry
from berg_agents.ui import cli_ui
from berg_agents.ui.web import app
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from rich.console import Console

# ---------------------------------------------------------------------------
# Dummy capabilities (no network required)
# ---------------------------------------------------------------------------


class _PingInput(BaseModel):
    """Empty input contract for the ping test capability."""


class _PingOutput(BaseModel):
    """Output contract for the ping test capability."""

    text: str


class PingCapability(CapabilityBase):
    """No-parameter test capability returning a fixed pong.

    Attributes
        id (str): The capability identifier.
        intent (str): A natural-language description of the capability.
        input_model (type[BaseModel]): The Pydantic model for inputs.
        output_model (type[BaseModel]): The Pydantic model for outputs.
        risk_class (RiskClass): The assessed risk of executing this capability.
        _execute (Callable[[BaseModel], BaseModel]): The implementation.
    """

    id = "ping"
    intent = "Ping the agent and get a pong back"
    input_model = _PingInput
    output_model = _PingOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:  # ruff: ignore[no-self-use]
        """Return a fixed pong.

        :param params: The invocation parameters (ignored).
        :return: A fixed pong.
        """
        return _PingOutput(text="pong")


class _AddInput(BaseModel):
    """Input contract carrying a single integer.

    Attributes
        a (int): The integer to increment.
    """

    a: int


class _AddOutput(BaseModel):
    """Output contract carrying the incremented integer.


    Attributes
        total (int): The incremented integer.
    """

    total: int


class AddCapability(CapabilityBase):
    """Test capability that increments its integer parameter.


    Attributes
        id (str): The capability identifier.
        intent (str): A natural-language description of the capability.
        input_model (type[BaseModel]): The Pydantic model for inputs.
        output_model (type[BaseModel]): The Pydantic model for outputs.
        risk_class (RiskClass): The assessed risk of executing this capability.
        _execute (Callable[[BaseModel], BaseModel]): The implementation.
     ```
    """

    id = "add"
    intent = "Add one to the supplied integer"
    input_model = _AddInput
    output_model = _AddOutput
    risk_class = RiskClass.LOW

    def _execute(self, params: BaseModel) -> BaseModel:  # ruff: ignore[no-self-use]
        """Increment the input integer and return it.


        :param params: The invocation parameters.
        :return: The incremented integer.
        """
        add_input = _AddInput.model_validate(params)
        return _AddOutput(total=add_input.a + 1)


def _make_registry() -> CapabilityRegistry:
    """Return a fresh registry with the two dummy capabilities registered.


    :return: A new registry with the dummy capabilities registered.
    """
    registry = CapabilityRegistry()
    registry.register(PingCapability())  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    registry.register(AddCapability())  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    return registry


def _capture_console() -> tuple[Console, Callable[[], str]]:
    """Return a recording Console and a callable that exports its text.


    :return: A console configured to record output and a zero-argument callable
        that returns all text written to the console.
    """
    console = Console(record=True, file=io.StringIO(), width=100)
    return console, console.export_text


# ---------------------------------------------------------------------------
# Catalog + request/progress/response/receipt rendering
# ---------------------------------------------------------------------------


def test_render_catalog_lists_every_capability() -> None:
    """The catalog table must show each registered capability's id + intent.

    :raise Exception("not yet implemented")
        Not yet implemented.
    :raise AssertionError
        If the catalog fails to render the expected capabilities.
    :raise NotImplementedError
        If the capability registry is empty or the renderer is not yet
        implemented.
    :raise Exception
        If the capability registry is empty or the renderer is not yet
        implemented.
    """
    console, export = _capture_console()
    cli_ui.render_catalog(_make_registry(), console)
    text = export()
    assert "Capability Catalog" in text
    assert "ping" in text
    assert "add" in text
    assert "Ping the agent" in text


def test_render_request_panel_shows_fields() -> None:
    """The request panel must surface the request id and capability id.


    :raise AssertionError
        If the request panel fails to render the expected fields.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    """
    console, export = _capture_console()
    request = InvocationRequest(request_id="r1", capability_id="ping")
    cli_ui.render_request(request, console)
    text = export()
    assert "r1" in text
    assert "ping" in text
    assert "Invocation request" in text


def test_render_progress_shows_capability_and_request() -> None:
    """The progress line must name the capability and request being run.

    :raise AssertionError
        If the progress line fails to render the expected fields.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    """
    console, export = _capture_console()
    request = InvocationRequest(request_id="r9", capability_id="add")
    cli_ui.render_progress(request, console)
    text = export()
    assert "add" in text
    assert "r9" in text
    assert "dispatching" in text.lower()


def test_render_response_success_is_green() -> None:
    """A successful response renders its result and a success title.


    :raise AssertionError
        If the response fails to render the expected fields.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    """
    console, export = _capture_console()
    response = InvocationResponse(
        request_id="r1",
        capability_id="ping",
        status="ok",
        result={"text": "pong"},
        duration_ms=12,
    )
    cli_ui.render_response(response, console)
    text = export()
    assert "succeeded" in text.lower()
    assert "pong" in text


def test_render_response_error_is_red() -> None:
    """An error response renders the inline message, never a traceback.


    :raise AssertionError
        If the response fails to render the expected fields.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    """
    console, export = _capture_console()
    response = InvocationResponse(
        request_id="r1",
        capability_id="ping",
        status="error",
        error="invalid params",
    )
    cli_ui.render_response(response, console)
    text = export()
    assert "failed" in text.lower()
    assert "invalid params" in text


def test_render_receipt_shows_hash_chain() -> None:
    """The receipt panel must expose the prev/receipt hash linkage.


    :raise AssertionError
        If the receipt fails to render the expected fields.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    """
    console, export = _capture_console()
    receipt = Receipt(
        request_id="r1",
        capability_id="ping",
        status="ok",
        timestamp="2026-08-05T00:00:00",
        prev_hash="GENESIS",
        receipt_hash="abc123",
    )
    cli_ui.render_receipt(receipt, console)
    text = export()
    assert "prev_hash" in text
    assert "receipt_hash" in text
    assert "abc123" in text


# ---------------------------------------------------------------------------
# Interactive loop (run_cli_ui)
# ---------------------------------------------------------------------------


def _input_sequence(answers: list[str]) -> Callable[[str], str]:
    """Return a read-line callable that yields ``answers`` in order.


    :param answers: The sequence of answers to yield.
    :return: A zero-argument callable that returns the next answer on each
        call, raising ``StopIteration`` when exhausted.
    :raise StopIteration
        When the sequence is exhausted.
    :raise Exception
        When the sequence is exhausted.
    """
    iterator: Iterator[str] = iter(answers)

    def _read(_prompt: str) -> str:
        """Return the next answer.

        :param _prompt: Ignored; the prompt to display.
        :return: The next answer.
        """
        return next(iterator)

    return _read


def test_run_cli_ui_quits_without_dispatch() -> None:
    """Selecting quit immediately must render the catalog and exit.


    :raise AssertionError
        If the exit condition is not detected or the catalog is not rendered.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    :raise StopIteration
        If the input sequence is exhausted.
    :raise Exception
        If the input sequence is exhausted.
    """
    console, export = _capture_console()
    cli_ui.run_cli_ui(_make_registry(), console, _input_sequence(["q"]))
    text = export()
    assert "Capability Catalog" in text
    assert "Goodbye" in text


def test_run_cli_ui_dispatches_no_param_capability() -> None:
    """A no-parameter capability is dispatched and its receipt rendered.

    :raise AssertionError
        If the capability is not dispatched or the receipt is not rendered.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    :raise StopIteration
        If the input sequence is exhausted.
    :raise Exception
        If the input sequence is exhausted.

    """
    console, export = _capture_console()
    cli_ui.run_cli_ui(_make_registry(), console, _input_sequence(["ping", "q"]))
    text = export()
    assert "succeeded" in text.lower()
    assert "Audit receipt" in text
    assert "Goodbye" in text


def test_run_cli_ui_coerces_and_dispatches_param() -> None:
    """An integer parameter is coerced and the capability result shown.

    :raise AssertionError
        If the parameter is not coerced or the result is not shown.
    :raise NotImplementedError
        If the renderer is not yet implemented.
    :raise Exception
        If the renderer is not yet implemented.
    :raise StopIteration
        If the input sequence is exhausted.
    :raise Exception
        If the input sequence is exhausted.

    """
    console, export = _capture_console()
    cli_ui.run_cli_ui(
        _make_registry(), console, _input_sequence(["add", "5", "q"])
    )
    text = export()
    assert "succeeded" in text.lower()
    assert "6" in text  # 5 + 1 from AddCapability


# ---------------------------------------------------------------------------
# Web UI endpoint (isolated registry via monkeypatch)
# ---------------------------------------------------------------------------


@pytest.fixture()
def web_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient whose registry is the isolated dummy registry.

    :param monkeypatch: The pytest fixture.
    :return: A FastAPI TestClient instance.
    :raise Exception
        If the registry cannot be patched or the client cannot be created.
    """
    monkeypatch.setattr(
        "berg_agents.ui.langgraphchatserver.LangGraphChatServer._get_registry",
        lambda self: _make_registry(),
        raising=True,
    )
    return TestClient(app)


def test_web_capabilities_listed(web_client: TestClient) -> None:
    """GET /capabilities returns 200 and lists the dummy capabilities.

    :param web_client: The TestClient instance.
    :raise AssertionError
        If the response is not 200 or the capabilities are not listed.
    :raise Exception
        If the response is not 200 or the capabilities are not listed.

    """
    response = web_client.get("/capabilities")
    assert response.status_code == 200
    catalog = response.json()
    ids = {entry["id"] for entry in catalog}
    assert "ping" in ids
    assert "add" in ids


def test_web_capabilities_proxied_through_vite_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /capabilities returns JSON when called through the Vite proxy target.


    :param monkeypatch: The pytest fixture.
    :raise AssertionError
        If the response is not 200 or the capabilities are not listed.
    :raise Exception
        If the response is not 200 or the capabilities are not listed.

    """
    monkeypatch.setattr(
        "berg_agents.ui.langgraphchatserver.LangGraphChatServer._get_registry",
        lambda self: _make_registry(),
        raising=True,
    )

    from berg_agents.ui.web import app as web_app
    from fastapi.testclient import TestClient

    proxy_client = TestClient(web_app, base_url="http://localhost:5173")
    response = proxy_client.get("/capabilities")
    assert response.status_code == 200
    catalog = response.json()
    assert isinstance(catalog, list)
    ids = {entry["id"] for entry in catalog}
    assert "ping" in ids
    assert "add" in ids


def test_web_invoke_returns_response_and_receipt(
    web_client: TestClient,
) -> None:
    """POST /invoke dispatches a valid capability and returns receipt.

    :param web_client: The TestClient instance.

    :raise AssertionError
        If the response is not 200 or the receipt is not returned.
    :raise Exception
        If the response is not 200 or the receipt is not returned.
    """
    response = web_client.post(
        "/invoke",
        json={"capability_id": "ping", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["status"] == "ok"
    assert payload["response"]["result"] == {"text": "pong"}
    assert payload["receipt"]["capability_id"] == "ping"
    assert payload["receipt"]["receipt_hash"]


def test_web_invoke_unknown_capability_returns_400(
    web_client: TestClient,
) -> None:
    """POST /invoke with an unknown id returns HTTP 400.

    :param web_client: The TestClient instance.
    :raise AssertionError
        If the response is not 400.
    :raise Exception
        If the response is not 400.

    """
    response = web_client.post(
        "/invoke",
        json={"capability_id": "nope", "params": {}},
    )
    assert response.status_code == 400
