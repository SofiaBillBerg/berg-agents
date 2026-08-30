"""Rich terminal UI for the capability layer.

Renders the capability catalog, drives an interactive invocation session
against a :class:`CapabilityRegistry`, and displays the resulting
:class:`InvocationResponse` and hash-chained audit :class:`Receipt` using
the ``rich`` library.

Every rendering function accepts an injectable
:class:`rich.console.Console` so tests can capture output; the interactive
loop accepts an injectable read-line callable for the same reason. Errors
returned by the registry are rendered inline - raw stack traces are never
leaked to the user.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any
import uuid

from berg_agents.capabilities.audit import Receipt
from berg_agents.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from berg_agents.capabilities.registry import CapabilityRegistry
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

def _risk_style(risk_class: str) -> str:
    """Return a rich style token for a risk class.

    :param risk_class: One of the :data:`berg_agents.capabilities.RiskClass` values.

    :return: A rich style name: green for low, yellow for medium, red for high,
        white for anything else.
    """
    return {
        "low": "green",
        "medium": "yellow",
        "high": "red",
    }.get(risk_class.lower(), "white")


def _coerce_param(raw: str, prop: dict[str, Any]) -> Any:
    """Coerce raw user input to the JSON-schema declared type.

    Unparsable values fall back to the raw string rather than aborting the
    session, keeping interactive input robust.

    :param raw: The raw string entered by the user.
    :param prop: The JSON schema property describing the parameter.

    :return: The coerced value, or ``raw`` when coercion fails.
    """
    json_type = prop.get("type", "string")
    try:
        if json_type == "integer":
            return int(raw)
        if json_type == "number":
            return float(raw)
        if json_type == "boolean":
            lowered = raw.lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            raise ValueError(f"not a boolean: {raw}")
        if json_type in {"array", "object"}:
            return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        # Coercion is best-effort; keep the raw value instead of failing.
        pass
    return raw


def _prompt_params(
    capability_meta: dict[str, Any],
    read_line: Callable[[str], str],
    console: Console,
) -> dict[str, Any]:
    """Collect typed parameters for a capability from the user.

    Each property of the capability's input JSON schema is prompted for.
    Optional parameters may be skipped by pressing enter; required ones that
    are skipped are simply omitted from the request (the registry's own
    validation reports any missing field).

    :param capability_meta: One entry from :meth:`CapabilityRegistry.discover`.
    :param read_line: Callable that reads a line of user input.
    :param console: Output console.

    :return: A dict of parameter name -> value suitable for an :class:`InvocationRequest`.
    """
    schema = capability_meta.get("input_schema", {})
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    required = set(schema.get("required", []))
    params: dict[str, Any] = {}

    if not properties:
        console.print("[dim]This capability takes no parameters.[/dim]")
        return params

    console.print("Supply parameters ([dim]enter to skip optional[/dim]):")
    for param_name, prop in properties.items():
        label = f"{param_name} ({prop.get('type', 'any')})"
        if param_name in required:
            label += " [red]*[/red]"
        raw = read_line(f"  {label}: ").strip()
        if not raw:
            if param_name in required:
                console.print(
                    f"[yellow]Skipped required parameter '{param_name}'.[/yellow]"
                )
            continue
        params[param_name] = _coerce_param(raw, prop)
    return params


def _select_capability(
    catalog: list[dict[str, Any]],
    raw: str,
    console: Console,
) -> dict[str, Any] | None:
    """Resolve a user selection (1-based index or capability id) to an entry.

    :param catalog: Entries from :meth:`CapabilityRegistry.discover`.
    :param raw: The raw user input.
    :param console: Output console.
    :return: The selected catalog entry, or ``None`` when nothing matches.
    """
    text = raw.strip().lower()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(catalog):
            return catalog[index]
        console.print(f"[yellow]No capability at index {int(text)}.[/yellow]")
        return None
    for entry in catalog:
        if entry["id"].lower() == text:
            return entry
    console.print(f"[yellow]Unknown capability '{raw.strip()}'.[/yellow]")
    return None


def render_catalog(
    registry: CapabilityRegistry, console: Console | None = None
) -> None:
    """Render the capability catalog as a rich table.

    Each row shows the selection index, the capability ``id``, its ``intent``
    and its ``risk_class`` (color-coded by severity).

    :param registry: The registry whose capabilities are listed.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    table = Table(title="Capability Catalog", header_style="bold magenta")
    table.add_column("#", justify="right", style="dim")
    table.add_column("id", style="cyan")
    table.add_column("intent")
    table.add_column("risk class", justify="center")
    for index, capability in enumerate(registry.discover(), start=1):
        table.add_row(
            str(index),
            capability["id"],
            capability["intent"],
            Text(
                capability["risk_class"],
                style=_risk_style(capability["risk_class"]),
            ),
        )
    console.print(table)


def render_request(
    request: InvocationRequest, console: Console | None = None
) -> None:
    """Render an invocation request as a rich panel.

    :param request: The request to display.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    lines = [
        f"request_id: {request.request_id}",
        f"capability: {request.capability_id}",
        f"caller: {request.caller or 'anonymous'}",
        f"params: {json.dumps(request.params, indent=2, default=str)}",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="Invocation request",
            border_style="blue",
        )
    )


def render_progress(
    request: InvocationRequest, console: Console | None = None
) -> None:
    """Render a tool-call progress indicator for a pending dispatch.

    Shown immediately before :meth:`CapabilityRegistry.dispatch` runs, so
    the user sees which capability and request id are being executed.

    :param request: The request being dispatched.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    console.print(
        f"[dim]→ dispatching '{request.capability_id}' "
        f"(request {request.request_id}) ...[/dim]"
    )


def render_response(
    response: InvocationResponse, console: Console | None = None
) -> None:
    """Render an invocation response as a rich panel.

    Successful responses show the structured result with a green border;
    error responses show a short inline message with a red border. Raw
    tracebacks are never printed.

    :param response: The response to display.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    if response.status == "error":
        message = Text(response.error or "unknown error", style="red")
        console.print(
            Panel(
                message,
                title=f"Invocation failed ({response.capability_id})",
                border_style="red",
            )
        )
        return
    result = json.dumps(response.result, indent=2, default=str)
    console.print(
        Panel(
            result,
            title=(
                f"Invocation succeeded ({response.capability_id}) "
                f"in {response.duration_ms} ms"
            ),
            border_style="green",
        )
    )


def render_receipt(receipt: Receipt, console: Console | None = None) -> None:
    """Render an audit receipt (hash-chained) as a rich panel.

    Displays the receipt's linkage fields - ``prev_hash`` and
    ``receipt_hash`` - so the tamper-evident chain is visible to the user.

    :param receipt: The receipt to display.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    lines = [
        f"request_id: {receipt.request_id}",
        f"capability: {receipt.capability_id}",
        f"status: {receipt.status}",
        f"timestamp: {receipt.timestamp}",
        f"prev_hash: {receipt.prev_hash}",
        f"receipt_hash: {receipt.receipt_hash}",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="Audit receipt",
            subtitle="hash-chained",
            border_style="cyan",
        )
    )


def run_cli_ui(
    registry: CapabilityRegistry,
    console: Console | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> None:
    """Run the interactive capability CLI session.

    Renders the capability catalog, then repeatedly prompts for a capability
    (by index or id), collects its parameters and dispatches an
    :class:`InvocationRequest`. Every dispatch renders the request, a
    progress line, the resulting response and the audit receipt.

    :param registry: The registry to render and dispatch against.
    :param console: Output console; defaults to a new :class:`Console`.
    :param input_fn: Read-a-line callable; defaults to the builtin ``input``.
    :return: None
    """
    console = console or Console()
    read_line = input_fn or input
    catalog = registry.discover()

    render_catalog(registry, console)

    while True:
        try:
            raw = read_line(
                "Select a capability (#, id, or 'q' to quit): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return
        if not raw or raw.lower() in {"q", "quit", "exit"}:
            console.print("[dim]Goodbye.[/dim]")
            return

        capability = _select_capability(catalog, raw, console)
        if capability is None:
            continue

        params = _prompt_params(capability, read_line, console)
        request = InvocationRequest(
            request_id=uuid.uuid4().hex,
            capability_id=capability["id"],
            params=params,
            caller="cli-ui",
        )

        try:
            render_request(request, console)
            render_progress(request, console)
            response, receipt = registry.dispatch(request)
        except Exception as exc:
            console.print(
                Panel(
                    Text(f"dispatch error: {exc}", style="red"),
                    title="Invocation failed",
                    border_style="red",
                )
            )
            continue

        render_response(response, console)
        render_receipt(receipt, console)
        console.print()
