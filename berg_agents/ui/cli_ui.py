# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Rich terminal UI for the harness layer.

Renders the agent catalog, drives an interactive task session against a
:class:`berg_agents.core.harness.Harness`, and displays results, learning
statistics, and human-review prompts using the ``rich`` library.

Every rendering function accepts an injectable
:class:`rich.console.Console` so tests can capture output; the interactive
loop accepts an injectable read-line callable for the same reason. Errors
are rendered inline - raw stack traces are never leaked to the user.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from berg_agents.core.harness import Harness
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__all__ = [
    "SLASH_COMMANDS",
    "render_agents",
    "render_help",
    "render_history",
    "render_result",
    "render_stats",
    "run_cli_ui",
    "run_harness_task",
    "run_tui"]

# Canonical slash commands. Names, descriptions, and categories mirror the
# web UI picker (``webapp/app/components/SlashCommandPicker.tsx``) so both
# surfaces list identical commands; subtask_16 owns keeping them in sync.
SLASH_COMMANDS: list[dict[str, str]] = [
    {
        "name": "/help",
        "description": "Show available commands",
        "category": "system"},
    {
        "name": "/agents",
        "description": "List registered agents",
        "category": "agents"},
    {
        "name": "/models",
        "description": "Show available models",
        "category": "models"},
    {
        "name": "/stats",
        "description": "Learning statistics",
        "category": "stats"},
    {
        "name": "/tools",
        "description": "List available tools",
        "category": "tools"},
    {
        "name": "/health",
        "description": "System health check",
        "category": "system"},
    {
        "name": "/history",
        "description": "Show conversation history",
        "category": "context"},
    {
        "name": "/memory",
        "description": "Memory information",
        "category": "context"},
    {
        "name": "/context",
        "description": "Show current context",
        "category": "context"},
    {"name": "/settings", "description": "Show settings", "category": "config"},
    {"name": "/skills", "description": "List skills", "category": "config"},
    {"name": "/mcps", "description": "MCP server status", "category": "config"},
    {
        "name": "/harness",
        "description": "Run task through harness",
        "category": "agents"},
    {"name": "/task", "description": "Same as /harness", "category": "agents"},
    {
        "name": "/clear",
        "description": "Clear conversation",
        "category": "system"}]

# Commands the TUI executes against the Harness. The rest are listed in
# /help for parity with the web UI but answered with a web-only notice:
# they query server-side state (providers, models, MCP servers) that the
# Harness API does not expose, and inventing answers would be fake.
_TUI_HANDLED = frozenset({
    "/help",
    "/agents",
    "/harness",
    "/task",
    "/stats",
    "/history",
    "/clear"})

_APPROVE_WORDS = frozenset({"y", "yes", "approve"})


def _success_rate(record: Mapping[str, Any] | None) -> int:
    """Return the rounded success percentage for one outcome record.

    :param record: Mapping with ``success``/``failure`` counts.
    :return: Integer percentage, 0 when nothing was recorded.
    """
    success = record.get("success", 0) if record else 0
    failure = record.get("failure", 0) if record else 0
    total = success + failure
    return round((success / total) * 100) if total else 0


def _outcome_total(record: Mapping[str, Any] | None) -> int:
    """Return the total recorded outcomes for one outcome record.

    :param record: Mapping with ``success``/``failure`` counts.
    :return: Sum of successes and failures.
    """
    if not record:
        return 0
    return int(record.get("success", 0)) + int(record.get("failure", 0))


def render_agents(
    agents: list[dict[str, Any]], console: Console | None = None
) -> None:
    """Render the harness agent catalog as a rich table.

    :param agents: Entries from :meth:`Harness.get_agent_info`.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    table = Table(title="Agent Catalog", header_style="bold magenta")
    table.add_column("name", style="cyan")
    table.add_column("description")
    table.add_column("complexity", justify="center")
    table.add_column("capabilities")
    for agent in agents:
        capabilities = agent.get("capabilities") or []
        table.add_row(
            str(agent.get("name", "unknown")),
            str(agent.get("description", "")),
            str(agent.get("preferred_complexity", "-")),
            ", ".join(str(cap) for cap in capabilities) or "-",
        )
    console.print(table)


def render_result(
    result: dict[str, Any], console: Console | None = None
) -> None:
    """Render one harness task result as a rich panel.

    Completed results show the selected agent, model, complexity, and
    risk with a green border; ``needs_human_review`` results show the review
    reasons with a yellow border; anything else shows the failure inline
    with a red border. Raw tracebacks are never printed.

    :param result: The dict returned by :meth:`Harness.execute_task`.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    status = result.get("status", "failed")
    if status == "completed":
        lines = [
            f"task_id: {result.get('task_id', '-')}",
            f"agent: {result.get('selected_agent', '-')}",
            f"model: {result.get('model', '-')}",
            f"complexity: {result.get('complexity', '-')}"]
        plan = result.get("plan")
        if isinstance(plan, dict):
            lines.append(f"plan steps: {len(plan.get('subtasks', []))}")
        console.print(
            Panel(
                "\n".join(lines),
                title=f"Task completed ({result.get('task_type', 'generic')})",
                subtitle=(
                    f"risk: {result.get('risk_level', '-')} "
                    f"confidence: {result.get('confidence', '-')}"
                ),
                border_style="green",
            )
        )
        return
    if status == "needs_human_review":
        reasons = result.get("review_reasons", [])
        body = (
            "\n".join(f"* {reason}" for reason in reasons) or "review requested"
        )
        console.print(
            Panel(
                body,
                title="Human review required",
                subtitle=(
                    f"risk: {result.get('risk_level', '-')} "
                    f"complexity: {result.get('complexity', '-')}"
                ),
                border_style="yellow",
            )
        )
        return
    message = Text(
        str(result.get("error") or result.get("status")), style="red"
    )
    console.print(
        Panel(
            message,
            title=f"Task failed ({result.get('task_type', 'generic')})",
            border_style="red",
        )
    )


def render_stats(
    stats: dict[str, Any] | None, console: Console | None = None
) -> None:
    """Render harness learning/outcome statistics as a rich table.

    :param stats: The mapping from :meth:`Harness.get_learning_stats`.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    total = (stats or {}).get("total", 0)
    if not total:
        console.print("[dim]No outcomes recorded yet.[/dim]")
        return
    table = Table(
        title=f"Learning stats ({total} tasks)", header_style="bold magenta"
    )
    table.add_column("group")
    table.add_column("success rate", justify="right")
    table.add_column("outcomes", justify="right")
    for group, records in (
        ("task type", (stats or {}).get("by_task_type", {})),
        ("model", (stats or {}).get("by_model", {})),
    ):
        for name, record in records.items():
            table.add_row(
                f"{group}: {name}",
                f"{_success_rate(record)}%",
                str(_outcome_total(record)),
            )
    console.print(table)


def render_help(console: Console | None = None) -> None:
    """Render the slash-command reference as a rich table.

    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    table = Table(title="Slash commands", header_style="bold magenta")
    table.add_column("command", style="cyan")
    table.add_column("description")
    table.add_column("category", justify="center")
    for command in SLASH_COMMANDS:
        table.add_row(
            command["name"], command["description"], command["category"]
        )
    console.print(table)


def render_history(
    entries: list[tuple[str, str]], console: Console | None = None
) -> None:
    """Render the in-session task transcript as a rich table.

    :param entries: ``(description, status)`` pairs in run order.
    :param console: Output console; defaults to a new :class:`Console`.
    :return: None
    """
    console = console or Console()
    if not entries:
        console.print("[dim]No tasks yet this session.[/dim]")
        return
    table = Table(title="Session history", header_style="bold magenta")
    table.add_column("#", justify="right", style="dim")
    table.add_column("task")
    table.add_column("status", justify="center")
    for index, (description, status) in enumerate(entries, start=1):
        table.add_row(
            str(index),
            description,
            Text(status, style="green" if status == "completed" else "yellow"),
        )
    console.print(table)


def run_harness_task(
    harness: Harness,
    description: str,
    task_type: str = "generic",
    metadata: dict[str, Any] | None = None,
    console: Console | None = None,
    read_line: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Execute one task through the harness with a human-review gate.

    Mirrors the web ``_run_stream_task`` resume contract: when the harness
    returns ``needs_human_review``, the user is prompted to approve; an
    approval re-executes with ``hitl_decision`` merged into the metadata,
    anything else fails the task as ``HITL rejected; task not resumed``.

    :param harness: The harness to execute against.
    :param description: Task description (must be non-empty).
    :param task_type: Task type label; ``generic`` by default.
    :param metadata: Optional metadata mapping for the task.
    :param console: Output console; defaults to a new :class:`Console`.
    :param read_line: Prompt callable for the review decision; defaults to
        the builtin ``input``.
    :return: The final harness result dict.
    """
    console = console or Console()
    prompt = read_line or input
    base_metadata = dict(metadata or {})
    console.print(f"[dim]→ running '{description}' ...[/dim]")
    try:
        result = harness.execute_task({
            "description": description,
            "task_type": task_type,
            "metadata": base_metadata})
    except Exception as exc:
        failed = {"status": "failed", "task_type": task_type, "error": str(exc)}
        render_result(failed, console)
        return failed

    if result.get("status") != "needs_human_review":
        render_result(result, console)
        return result

    render_result(result, console)
    try:
        answer = (
            prompt("Approve and resume? This will call the model. [y/N]: ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in _APPROVE_WORDS:
        failed = {
            "status": "failed",
            "task_type": task_type,
            "error": "HITL rejected; task not resumed"}
        render_result(failed, console)
        return failed
    try:
        resumed = harness.execute_task({
            "description": description,
            "task_type": task_type,
            "metadata": {**base_metadata, "hitl_decision": "approve"}})
    except Exception as exc:
        failed = {"status": "failed", "task_type": task_type, "error": str(exc)}
        render_result(failed, console)
        return failed
    render_result(resumed, console)
    return resumed


def _handle_slash_command(
    harness: Harness,
    raw: str,
    history: list[tuple[str, str]],
    console: Console,
    read_line: Callable[[str], str],
) -> str:
    """Handle one slash-command line; return ``"quit"`` to end the session.

    :param harness: The harness to render and execute against.
    :param raw: The raw input line, starting with ``/``.
    :param history: The in-session ``(description, status)`` transcript,
        extended in place when a task runs.
    :param console: Output console.
    :param read_line: Read-a-line callable for follow-up prompts.
    :return: ``"quit"`` when the session should end, else ``"continue"``.
    """
    command, _, argument = raw.partition(" ")
    command = command.lower()
    if command == "/help":
        render_help(console)
    elif command == "/agents":
        render_agents(harness.get_agent_info(), console)
    elif command in {"/harness", "/task"}:
        description = argument.strip()
        if not description:
            try:
                description = read_line("Task description: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye.[/dim]")
                return "quit"
            if not description:
                return "continue"
        result = run_harness_task(
            harness, description, "harness", None, console, read_line
        )
        history.append((description, str(result.get("status"))))
        console.print()
    elif command == "/stats":
        render_stats(harness.get_learning_stats(), console)
    elif command == "/history":
        render_history(history, console)
    elif command == "/clear":
        console.clear()
    elif command in _TUI_HANDLED:
        pass
    elif any(entry["name"] == command for entry in SLASH_COMMANDS):
        console.print(f"[dim]{command} is available in the web UI.[/dim]")
    else:
        console.print(f"[yellow]Unknown command '{raw}'.[/yellow]")
    return "continue"


def run_cli_ui(
    harness: Harness,
    console: Console | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> None:
    """Run the interactive harness terminal session.

    Renders the agent catalog, then repeatedly reads tasks or slash
    commands. Bare text runs a ``generic`` harness task; ``/harness`` (and
    its ``/task`` alias) run a task with explicit ``harness`` task type;
    ``/agents``, ``/stats``, ``/history``, ``/help``, and ``/clear`` inspect
    the session. Review-gated tasks pause for an inline approval/reject
    decision before resuming.

    :param harness: The harness to render and execute against.
    :param console: Output console; defaults to a new :class:`Console`.
    :param input_fn: Read-a-line callable; defaults to the builtin ``input``.
    :return: None
    """
    console = console or Console()
    read_line = input_fn or input
    history: list[tuple[str, str]] = []

    render_agents(harness.get_agent_info(), console)
    console.print(
        "[dim]Type /help for commands, or just describe a task.[/dim]"
    )

    while True:
        try:
            raw = read_line("harness> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            return
        if not raw:
            continue
        lowered = raw.lower()
        if lowered in {"q", "quit", "exit", "/quit"}:
            console.print("[dim]Goodbye.[/dim]")
            return

        if raw.startswith("/"):
            if (
                _handle_slash_command(harness, raw, history, console, read_line)
                == "quit"
            ):
                return
            continue

        result = run_harness_task(
            harness, raw, "generic", None, console, read_line
        )
        history.append((raw, str(result.get("status"))))
        console.print()


def run_tui() -> None:
    """Start the interactive terminal session from application configuration.

    Zero-argument entry point used by ``python -m berg_agents --tui``: builds
    the application :class:`Harness` from configuration and runs the
    interactive loop against it. The import is deferred so this module stays
    light for tests that only need the renderers.

    :return: None
    """
    from berg_agents.app import BergAgentsApp

    run_cli_ui(BergAgentsApp.create().harness)
