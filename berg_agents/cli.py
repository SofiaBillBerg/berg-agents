"""Command-line interface for the **berg_agents** package.

The CLI is intentionally small - it only exposes the most common
operations that a developer would want when working in a local
repository:

* ``create`` - create a new file with supplied content.
* ``append`` - append to an existing file.
* ``chat`` - start an interactive chat session with the agent.
* ``capabilities list`` - list the registered capabilities.
* ``capabilities invoke`` - dispatch an invocation through the registry.
* ``serve`` - start the LLM provider selected by the config.

Implementation details
----------------------
* Uses **Typer** for argument parsing - it provides a pleasant
  developer experience (automatic ``--help`` generation, type checking
  and rich error messages).
* ``create`` writes files atomically via
  :func:`berg_agents.tools._io._atomic_write`.
* ``capabilities`` commands build a :class:`CapabilityRegistry` populated
  with the default tools adapted via :func:`tool_to_capability`, then
  discover or dispatch through it.
* ``serve`` selects a provider via :func:`create_provider` from the config
  and runs a small read-eval-print loop against ``provider.complete``.
* Errors are wrapped in :class:`berg_agents.exceptions.CodeAgentError` to

The CLI is intentionally **stateless** - it performs the requested
action and exits.  All heavy lifting is done by the helper functions.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, cast
import uuid

from berg_agents.agents.codeagent import build_agent, create_default_tools
from berg_agents.capabilities.audit import Receipt
from berg_agents.capabilities.envelope import (
    InvocationRequest,
    InvocationResponse,
)
from berg_agents.capabilities.registry import CapabilityRegistry
from berg_agents.capabilities.tool_adapter import tool_to_capability
from berg_agents.config.mcp import apply_mcp_tool_prefixes, expand_env_vars
from berg_agents.config.settings import PROJECT_ROOT
from berg_agents.exceptions import CodeAgentError
from berg_agents.main import create_llm, load_config
from berg_agents.tools._io import _atomic_write
from langchain.chat_models import BaseChatModel
from langchain.messages import AIMessage
from langchain.tools import BaseTool
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.sessions import Connection
from langgraph.types import Command
import typer

# Module-level Typer argument/option definitions to avoid
# "function-call-in-default-argument" lint warnings.
# noinspection argument-equal-default
FILE_PATH_ARG_CREATE: Path = typer.Argument(
    ..., exists=False, help="Path to the file to create."
)
FILE_PATH_ARG_APPEND: Path = typer.Argument(
    ..., exists=True, help="Path to the file to modify."
)
app = typer.Typer(name="berg_agents", help="Local LLM-driven code assistant")


# ---------------------------------------------------------------------------
# Terminal UX helpers for the chat command
# ---------------------------------------------------------------------------


def _stream_agent_response(  # ruff: ignore[complex-structure]
    agent: Any,
    messages: list[Any],
    thread_id: str,
) -> str:
    """Run one agent turn, surfacing Human-in-the-Loop approval prompts.

    Streams visible progress to the terminal.  If the
    :class:`HumanInTheLoopMiddleware` interrupts the run (for example before
    writing or editing a file), the pending decisions are presented to the
    terminal user, who may approve, reject or respond.  The graph is then
    resumed with the collected decisions and the loop repeats until the run
    completes without an interrupt.

    :param agent: Compiled LangChain/LangGraph runnable (``create_agent``
        harness with an ``InMemorySaver`` checkpointer).
    :param messages: Messages for the first run of the turn (ignored on
        interrupt resumes, which use :class:`~langgraph.types.Command`).
    :param thread_id: Thread id for the checkpointer/config.
    :return: The final assistant text, or ``"(no text response)"`` when no
        assistant message is produced.
    """
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 150}
    run_input: Any = {"messages": messages}
    final_text_parts: list[str] = []
    final_messages: list[Any] = []

    # Bounded loop: stream a run, surface any HITL interrupts, resume, repeat.
    for _ in range(32):
        final_text_parts, final_messages = _run_agent_stream(
            agent, run_input, config
        )

        interrupts = _collect_hitl_requests(agent, config)
        if not interrupts:
            break

        decisions: list[dict[str, Any]] = []
        for hitl_request in interrupts:
            # HITLRequest is a TypedDict; after the checkpoint round-trip it
            # arrives as a plain dict, so access must work for both forms.
            action_requests = (
                hitl_request.get("action_requests", [])
                if isinstance(hitl_request, dict)
                else getattr(hitl_request, "action_requests", [])
            )
            for action_request in action_requests:
                decisions.append(_prompt_hitl_decision(action_request))
        run_input = Command(resume={"decisions": decisions})

    if final_text_parts:
        return "".join(final_text_parts)

    # Fallback: pull the final assistant message from the persisted state.
    try:
        state = agent.get_state(config)
        values = getattr(state, "values", {}) or {}
        for msg in reversed(values.get("messages", []) or []):
            if hasattr(msg, "content") and getattr(msg, "content", None):
                return str(msg.content)
    except Exception:  # ruff: ignore[try-except-pass]
        # Best-effort: a failed checkpointer read is non-fatal; we fall
        # through to the final_messages fallback below.
        pass  # ruff: ignore[try-except-continue]

    if final_messages:
        for msg in reversed(final_messages):
            if hasattr(msg, "content") and getattr(msg, "content", None):
                return str(msg.content)
    return "(no text response)"


def _run_agent_stream(  # ruff: ignore[complex-structure]
    agent: Any, run_input: Any, config: dict[str, Any]
) -> tuple[list[str], list[Any]]:
    """Stream one agent invocation and return ``(text_parts, messages)``.

    :return:
    :rtype:
    :param agent: Compiled runnable.
    :param run_input: Either ``{"messages": [...]}`` or a
        :class:`~langgraph.types.Command` used to resume an interrupt.
    :param config: LangGraph runnable config (thread id).
    :return: Tuple of streamed text chunks and the final message list.
    """
    final_text_parts: list[str] = []
    final_messages: list[Any] = []

    spinner_running = True
    spinner_text = itertools.cycle(["Thinking", "Working", "Running"])

    def _spin() -> None:
        """Spin the spinner until the agent run completes."""
        while spinner_running:
            label = next(spinner_text)
            print(f"\r\033[K{label}...", end="", flush=True)
            time.sleep(0.35)

    thread = threading.Thread(target=_spin, daemon=True)
    thread.start()

    async def _consume(stream_fn: Any) -> tuple[list[str], list[Any]]:
        """Consume the async ``astream_events`` generator.

        LangGraph's ``astream_events`` is an **async** generator, so it must
        be driven from an event loop.  ``asyncio.run`` below provides one;
        this inner coroutine keeps the callback-style event processing
        (``on_tool_start``/``on_chat_model_stream``/...) intact.
        """
        text_parts: list[str] = []
        messages: list[Any] = []
        async for event in stream_fn(run_input, config=config, version="v2"):
            kind = event.get("event")
            data = event.get("data", {})
            if kind == "on_tool_start":
                name = (
                    data.get("input", {}).get("query")
                    or data.get("name")
                    or "tool"
                )
                print(f"\r\033[K🔧 Tool start: {name}")
            elif kind == "on_tool_end":
                print("\r\033[K✅ Tool end")
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is not None:
                    content = getattr(chunk, "content", None)
                    if content:
                        print(content, end="", flush=True)
                        text_parts.append(content)
            elif kind == "on_chain_end" and data.get("output"):
                output = data["output"]
                if isinstance(output, dict):
                    messages = output.get("messages", [])
        return text_parts, messages

    try:  # ruff: ignore[too-many-statements-in-try-clause]
        stream_fn = getattr(agent, "astream_events", None)
        if stream_fn is None:
            raise AttributeError("astream_events")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop in this thread: safe to drive the async
            # generator with a fresh event loop.
            final_text_parts, final_messages = asyncio.run(_consume(stream_fn))
        else:
            # Already inside an event loop (async embedding): fall back to a
            # plain sync invoke instead of crashing.
            response = agent.invoke(run_input, config=config)
            if isinstance(response, dict):
                final_messages = response.get("messages", [])
    except Exception:
        response = agent.invoke(run_input, config=config)
        if isinstance(response, dict):
            final_messages = response.get("messages", [])
    finally:
        spinner_running = False
        thread.join(timeout=1)
        print("\r\033[K", end="", flush=True)

    return final_text_parts, final_messages


def _collect_hitl_requests(agent: Any, config: dict[str, Any]) -> list[Any]:
    """Return the list of HITL request payloads currently interrupting *agent*.

    Reads the persisted graph state for *config* and collects the
    ``interrupt()`` payloads (the ``HITLRequest`` objects emitted by
    :class:`HumanInTheLoopMiddleware`) from any pending tasks.

    :param agent: Compiled runnable.
    :param config: LangGraph runnable config (thread id).
    :return: List of interrupt payloads (empty when not interrupted).
    """
    try:
        state = agent.get_state(config)
    except Exception:
        return []
    interrupts: list[Any] = []
    for task in getattr(state, "tasks", []) or []:
        interrupts.extend(getattr(task, "interrupts", []) or [])
    return [interrupt.value for interrupt in interrupts]


def _prompt_hitl_decision(action_request: Any) -> dict[str, Any]:
    """Present one pending tool action to the user and collect a decision.

    The returned dict matches the contract consumed by
    :class:`HumanInTheLoopMiddleware`: exactly one decision per interrupted
    tool call with a ``type`` of ``"approve"``, ``"reject"``, ``"respond"``
    or ``"edit"``.

    :param action_request: The ``ActionRequest`` describing the tool call the
        agent wants to execute.
    :return: A decision dict for the ``Command(resume=...)`` payload.
    """
    if isinstance(action_request, dict):
        name = action_request.get("name", "unknown-tool")
        args = action_request.get("args", {}) or {}
    else:
        name = getattr(action_request, "name", "unknown-tool")
        args = getattr(action_request, "args", {}) or {}

    print("\n" + "=" * 50)
    print("⚠️  Human approval required before tool execution")
    print(f"Tool: {name}")
    try:
        print(f"Args:\n{json.dumps(args, indent=2, default=str)}")
    except (TypeError, ValueError):
        print(f"Args: {args!r}")
    description = (
        action_request.get("description")
        if isinstance(action_request, dict)
        else getattr(action_request, "description", None)
    )
    if description:
        print(f"\n{description}")
    print("=" * 50)
    print("Decide: [a]pprove  [r]eject  [e]dit  [m]essage")

    choice = input("Your decision: ").strip().lower()
    if choice in {"r", "reject"}:
        reason = input("Reason (optional): ").strip()
        return {"type": "reject", "message": reason or None}
    if choice in {"m", "message", "respond"}:
        message = input("Message to send back to the agent: ").strip()
        return {"type": "respond", "message": message}
    if choice in {"e", "edit"}:
        print(
            "Provide the edited tool arguments as JSON (Enter keeps original):"
        )
        raw = input("Edited args: ").strip()
        if raw:
            try:
                edited_args = json.loads(raw)
            except json.JSONDecodeError:
                print("Invalid JSON - falling back to approve.")
                return {"type": "approve"}
            return {
                "type": "edit",
                "edited_action": {"name": name, "args": edited_args},
            }
        return {"type": "approve"}
    # Default to approve for any unrecognized input.
    return {"type": "approve"}


def _build_registry(root_dir: str | None = None) -> CapabilityRegistry:
    """Build a registry populated with the default tool-adapted capabilities.

    Each default tool that can be constructed without an LLM is wrapped via
    :func:`tool_to_capability` and registered under its kebab-cased id. Tools
    that require an LLM (e.g. ``search-explain``, ``generate-test``) are
    intentionally omitted so ``capabilities`` commands stay stateless and do
    not require a running model backend.

    :param root_dir: Root directory the tools operate within; defaults to the
            current working directory.

    :return: A :class:`CapabilityRegistry` with the adapted tools registered.
    """
    registry = CapabilityRegistry()
    for tool in create_default_tools(root_dir=root_dir):
        # tool_to_capability returns a compatible runtime object, but static
        # protocol variance around writable attributes causes a false-positive.
        registry.register(capability=cast(Any, tool_to_capability(tool)))
    return registry


def _echo_response(response: InvocationResponse, receipt: Receipt) -> None:
    """Print an invocation response and its audit receipt.

    :param response: The invocation response to display.
    :param receipt: The audit receipt recorded for the dispatch.
    :return: None
    """
    if response.status == "error":
        typer.echo("status: error")
        typer.echo(f"error: {response.error}")
    else:
        typer.echo("status: ok")
        typer.echo(f"result: {json.dumps(response.result, default=str)}")
    typer.echo(f"duration_ms: {response.duration_ms}")
    typer.echo(
        f"receipt: request_id={receipt.request_id} "
        f"status={receipt.status} timestamp={receipt.timestamp} "
        f"receipt_hash={receipt.receipt_hash}"
    )


capabilities_app = typer.Typer(
    help="Inspect and invoke the registered capabilities."
)
app.add_typer(capabilities_app, name="capabilities")


@capabilities_app.command("list", help="List all registered capabilities.")
def capabilities_list() -> None:
    """List every registered capability (id, intent, risk class).

    The catalog is built from the default tools adapted into capabilities.
    Each row shows the capability ``id``, its ``risk_class`` and its
    ``intent`` (a human description of what the capability does).

    :return: None
    """
    capabilities = _build_registry().discover()
    if not capabilities:
        typer.echo("No capabilities registered.")
        return

    rows: list[tuple[str, str, str]] = [
        (cap["id"], cap["risk_class"], cap["intent"]) for cap in capabilities
    ]
    id_width = max(len(row[0]) for row in rows)
    risk_width = max(len(row[1]) for row in rows)
    for cap_id, risk_class, intent in rows:
        typer.echo(
            f"{cap_id:<{id_width}}  {risk_class:<{risk_width}}  {intent}"
        )


@capabilities_app.command(
    "invoke", help="Dispatch a request through the registry."
)
def capabilities_invoke(
    capability_id: str = typer.Argument(
        ..., help="Identifier of the capability to invoke."
    ),
    params: str = typer.Option(
        "{}", help="JSON object of invocation parameters."
    ),
) -> None:
    """Invoke a capability and print the response and audit receipt.

    Builds an :class:`InvocationRequest` for ``capability_id`` with the
    supplied ``params`` (a JSON object), dispatches it through the registry
    and prints the resulting :class:`InvocationResponse` together with the
    hash-chained audit :class:`Receipt`. A non-zero exit code is returned
    when the dispatch reports an error.

    :param capability_id: Stable identifier of the capability to invoke.
    :param params: JSON object of parameters for the capability.
    :return: None
    """
    try:
        parsed_params: dict[str, Any] = json.loads(params)
    except json.JSONDecodeError as exc:
        raise CodeAgentError(f"Invalid --params JSON: {exc}") from exc

    request = InvocationRequest(
        request_id=uuid.uuid4().hex,
        capability_id=capability_id,
        params=parsed_params,
        caller="cli",
    )
    response, receipt = _build_registry().dispatch(request)
    _echo_response(response, receipt)
    if response.status == "error":
        raise typer.Exit(code=1)


def _ensure_webapp_built() -> None:
    """Build the React SPA into ``webapp/dist`` if it is missing.

    ``dist/`` is in gitignore, so a fresh checkout ships no built UI until the
    frontend is compiled. When Node/npm are available we build it lazily so
    ``berg_agents serve --web`` works out of the box. A missing toolchain is
    non-fatal: the API still serves, just without the static single-page app.

    :return: None
    """
    webapp_dir = Path(__file__).resolve().parent / "ui" / "webapp"
    dist_dir = webapp_dir / "dist"
    if dist_dir.is_dir():
        return
    if not webapp_dir.is_dir():
        typer.echo(
            "Note: webapp source not found; serving the API without the web UI.",
            err=True,
        )
        return
    npm = shutil.which("npm")
    if npm is None:
        typer.echo(
            "Note: webapp/dist not found and npm is not on PATH; serving the "
            "API without the web UI. Run `npm install && npm run build` in "
            "berg_agents/ui/webapp to build it.",
            err=True,
        )
        return
    typer.echo(
        "Building web UI into webapp/dist (npm install && npm run build)..."
    )
    try:
        subprocess.run(
            [npm, "install"],
            cwd=str(webapp_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [npm, "run", "build"],
            cwd=str(webapp_dir),
            check=True,
            capture_output=True,
            text=True,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ) as exc:  # pragma: no cover - environment dependent
        detail = (getattr(exc, "stderr", "") or "").strip() or str(exc)
        typer.echo(
            f"Warning: failed to build web UI ({detail}); serving API without it.",
            err=True,
        )


def _normalize_mcp_servers(raw: str) -> list[dict[str, Any]]:
    """Parse MCP server configs from inline JSON or a file path.

    Supports:
    * Inline JSON array of server configs
    * Inline JSON object ``{ "mcpServers": { name: cfg, ... } }``
    * Path to a JSON file containing either of the above shapes
    """
    value = raw.strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        servers = parsed
    elif isinstance(parsed, dict):
        if "mcpServers" in parsed:
            servers = [
                {"name": name, **cfg}
                for name, cfg in parsed["mcpServers"].items()
            ]
        else:
            servers = [parsed]
    else:
        servers = None

    if servers is None:
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            typer.echo(
                f"Warning: mcp_servers file not found: {path}; skipping MCP tools.",
                err=True,
            )
            return []
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            typer.echo(
                "Warning: invalid mcp_servers file JSON; skipping MCP tools.",
                err=True,
            )
            return []

        if isinstance(parsed, list):
            servers = parsed
        elif isinstance(parsed, dict):
            if "mcpServers" in parsed:
                servers = [
                    {"name": name, **cfg}
                    for name, cfg in parsed["mcpServers"].items()
                ]
            else:
                servers = [parsed]
        else:
            servers = []

    return [cfg for cfg in servers if cfg.get("enabled") is not False]


def _to_langchain_connection(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize an MCP server config to a langchain-mcp-adapters connection dict.

    :param cfg: A server config object.
    :return: A connection dict for langchain-mcp-adapters.
    """
    cfg = dict(cfg)
    cfg.pop("name", None)
    cfg.pop("enabled", None)

    mcp_type = cfg.pop("type", None)
    transport = None
    if mcp_type == "remote":
        transport = "http"
    elif mcp_type == "local":
        transport = "stdio"
    elif mcp_type in {"stdio", "sse", "http", "streamable_http", "websocket"}:
        transport = mcp_type

    if not transport:
        if "url" in cfg:
            transport = "http"
        elif "command" in cfg:
            transport = "stdio"

    if transport:
        cfg["transport"] = transport

    if "environment" in cfg:
        cfg["env"] = expand_env_vars(cfg.pop("environment"))

    if "headers" in cfg:
        cfg["headers"] = expand_env_vars(cfg["headers"])

    command = cfg.get("command")
    if isinstance(command, list):
        head = command[0]
        if isinstance(head, str) and " " in head:
            cfg["command"] = head.split()[0]
            cfg.setdefault("args", head.split()[1:] + command[1:])
        else:
            cfg["command"] = head
            cfg.setdefault("args", command[1:])

    if transport == "http":
        cfg.pop("oauth", None)

    return expand_env_vars(cfg)


def _ensure_dotenv() -> None:
    """Load secrets from a local, git-ignored ``.env`` into the environment.

    MCP server configs reference secrets as ``${VAR}`` placeholders. Those are
    resolved against ``os.environ`` at load time, so we populate the environment
    from ``.env`` if it exists. Existing variables are never overwritten.
    """
    dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_mcp_tools(cfg: dict[str, Any]) -> list[BaseTool]:
    """Load tools from configured MCP servers.

    Reads ``mcp_servers`` from *cfg*. The value may be either:

    * a JSON-encoded MCP server config object, or
    * a path to a JSON file containing a server config object.

    Tools are imported via ``langchain_mcp_adapters`` when available.
    Missing dependencies or malformed configs are logged and skipped
    so the rest of the agent still works.

    :param cfg: Configuration mapping, typically from :func:`load_config`.
    :return: A list of :class:`BaseTool` instances from MCP servers.
    """
    _ensure_dotenv()
    raw: str | None = cfg.get("mcp_servers")
    if not raw:
        return []

    servers = _normalize_mcp_servers(raw)
    if not servers:
        return []

    try:
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError:
        typer.echo(
            "Warning: langchain-mcp-adapters not installed; skipping MCP tools. "
            "Install it with: pip install langchain-mcp-adapters",
            err=True,
        )
        return []

    async def _load() -> list[BaseTool]:
        """Async helper to load tools from MCP servers.

        :return: A list of :class:`BaseTool` instances from MCP servers.
        """
        tools: list[BaseTool] = []
        for server_cfg in servers:
            connection = _to_langchain_connection(server_cfg)
            transport = connection.get("transport")
            if transport not in {
                "stdio",
                "sse",
                "http",
                "streamable_http",
                "websocket",
            }:
                typer.echo(
                    f"Warning: unsupported MCP server transport {transport!r}; skipping.",
                    err=True,
                )
                continue
            server_name = server_cfg.get("name", transport)
            try:
                server_tools = await load_mcp_tools(
                    None, connection=cast(Connection, connection)
                )
            except Exception as exc:  # pragma: no cover - external dependency
                typer.echo(
                    f"Warning: failed to load MCP tools from {server_name}: {exc}",
                    err=True,
                )
                continue
            tools.extend(apply_mcp_tool_prefixes(server_tools, server_name))
            typer.echo(
                f"Loaded {len(server_tools)} tool(s) from MCP server ({server_name})."
            )
        return tools

    try:
        return asyncio.run(_load())
    except Exception as exc:  # pragma: no cover - defensive guard
        typer.echo(f"Warning: failed to load MCP tools: {exc}", err=True)
        return []


async def _load_mcp_tools_async(cfg: dict[str, Any]) -> list[BaseTool]:
    """Async version of _load_mcp_tools for use in async contexts.

    Reads ``mcp_servers`` from *cfg*. The value may be either:

    * a JSON-encoded MCP server config object, or
    * a path to a JSON file containing a server config object.

    Tools are imported via ``langchain_mcp_adapters`` when available.
    Missing dependencies or malformed configs are logged and skipped
    so the rest of the agent still works.

    This async version can be awaited in FastAPI endpoints and other
    async contexts where asyncio.run() cannot be used.

    :param cfg: Configuration mapping, typically from :func:`load_config`.
    :return: A list of :class:`BaseTool` instances from MCP servers.
    """
    _ensure_dotenv()
    raw: str | None = cfg.get("mcp_servers")
    if not raw:
        return []

    servers = _normalize_mcp_servers(raw)
    if not servers:
        return []

    try:
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError:
        typer.echo(
            "Warning: langchain-mcp-adapters not installed; skipping MCP tools. "
            "Install it with: pip install langchain-mcp-adapters",
            err=True,
        )
        return []

    tools: list[BaseTool] = []
    for server_cfg in servers:
        connection = _to_langchain_connection(server_cfg)
        transport = connection.get("transport")
        if transport not in {
            "stdio",
            "sse",
            "http",
            "streamable_http",
            "websocket",
        }:
            typer.echo(
                f"Warning: unsupported MCP server transport {transport!r}; skipping.",
                err=True,
            )
            continue
        server_name = server_cfg.get("name", transport)
        try:
            server_tools = await load_mcp_tools(
                None, connection=cast(Connection, connection)
            )
        except Exception as exc:  # pragma: no cover - external dependency
            typer.echo(
                f"Warning: failed to load MCP tools from {server_name}: {exc}",
                err=True,
            )
            continue
        tools.extend(apply_mcp_tool_prefixes(server_tools, server_name))
        typer.echo(
            f"Loaded {len(server_tools)} tool(s) from MCP server ({server_name})."
        )
    return tools


@app.command(help="Start the LLM provider selected by the config.")
def serve(  # ruff: ignore [complex-structure]
    config_path: str | None = typer.Option(
        None,
        help="Optional path to a JSON configuration file (overrides .env settings).",
    ),
    web: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
        "--web",
        is_flag=True,
        help="Serve the web UI instead of the console loop.",
    ),
    web_host: str = typer.Option(
        "127.0.0.1",
        "--web-host",
        help="Host to bind the web UI server to.",
    ),
    web_port: int = typer.Option(
        8000,
        "--web-port",
        help="Port to bind the web UI server to.",
    ),
) -> None:
    """Start the provider selected by the config and serve prompts.

    Loads the config, constructs the provider via :func:`create_provider`
    and runs a small read-eval-print loop: each line of input is sent to
    ``provider.complete`` and the completion is printed. Type ``exit``,
    ``quit`` or ``q`` (or press Ctrl-C) to end the session.

    With ``--web`` the command instead starts a local HTTP server for the
    web UI (``berg_agents.ui.web``): ``GET /capabilities`` lists the
    capability catalog and ``POST /invoke`` dispatches audited invocations.
    The built React app is served from ``berg_agents/ui/webapp/dist`` when
    present. The server binds to ``127.0.0.1:8000``; pass ``--web-port`` to
    change the port. No API keys or prompt content are ever logged.

    :param config_path: Path to the JSON configuration file.
    :param web: Whether to serve the web UI instead of the console loop.
    :param web_host: Host to bind the web UI server to.
    :param web_port: Port to bind the web UI server to.
    :return: None
    """
    if web:
        _ensure_webapp_built()
        import uvicorn

        typer.echo(f"Web UI at http://{web_host}:{web_port}")
        uvicorn.run(
            "berg_agents.ui.web:app",
            host=web_host,
            port=web_port,
            log_level="info",
        )
        return

    try:  # ruff: ignore [too-many-statements-in-try-clause]
        from berg_agents.agents.codeagent import create_default_tools
        from berg_agents.main import create_llm

        cfg = load_config(config_path)
        llm = create_llm(cfg)
        tools = create_default_tools(root_dir=str(Path.cwd()), llm=llm)

        # Inject MCP tools if configured
        mcp_tools = _load_mcp_tools(cfg)
        if mcp_tools:
            tools.extend(mcp_tools)

        agent = build_agent(llm=llm, tools=tools)

        model_name = getattr(
            llm, "model", getattr(cfg, "ollama_model", "unknown")
        )
        thread_id = str(uuid.uuid4())
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(f"Failed to initialize agent: {exc}") from exc

    typer.echo(
        f"Serving agent with model '{model_name}' and {len(tools)} tools."
    )
    typer.echo("Type 'exit', 'quit' or 'q' to end the session.")
    typer.echo("Type 'tools' to list available tools.")

    conversation_history: list[dict[str, Any]] = []

    while True:
        try:
            prompt = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("\nGoodbye!")
            break
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit", "q"}:
            typer.echo("Goodbye!")
            break
        if prompt.lower() == "tools":
            typer.echo(f"Available tools: {', '.join(t.name for t in tools)}")
            continue
        if prompt.lower() == "clear":
            conversation_history = []
            typer.echo("Conversation history cleared.")
            continue
        try:  # ruff: ignore [too-many-statements-in-try-clause]
            from langchain.messages import HumanMessage, SystemMessage

            messages: list[BaseMessage] = [
                SystemMessage(content=cfg.get("system_prompt", ""))
            ]
            for entry in conversation_history:
                if entry["role"] == "assistant":
                    messages.append(AIMessage(content=entry["content"]))
                elif entry["role"] == "user":
                    messages.append(HumanMessage(content=entry["content"]))
            messages.append(HumanMessage(content=prompt))

            response = asyncio.run(
                agent.ainvoke(
                    {"messages": messages},
                    config={
                        "configurable": {"thread_id": thread_id},
                        "recursion_limit": 150,
                    },
                )
            )

            # Find the last AIMessage (skip ToolMessages from intermediate steps)
            ai_messages = [
                msg
                for msg in response["messages"]
                if isinstance(msg, AIMessage)
            ]
            if not ai_messages:
                response_content = "(no text response)"
            else:
                response_content = ai_messages[-1].content or "(empty response)"

            conversation_history.append({"role": "user", "content": prompt})
            conversation_history.append({
                "role": "assistant",
                "content": response_content,
            })
        except Exception as exc:
            typer.echo(f"Error: {exc}")
            continue
        typer.echo(f"Agent: {response_content}")


@app.command(help="Create a new file with the supplied content.")
def create(
    file_path: Path = FILE_PATH_ARG_CREATE,
    content: str = typer.Option(..., help="Content to write into the file."),
    overwrite: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
        is_flag=True,
        help="Allow overwriting an existing file.",
    ),
) -> None:
    """Create ``file_path`` with ``content``.

    The file is written atomically - a temporary file is written first
    and then renamed to the target path.  If the file already exists
    and ``overwrite`` is not set, the command exits with a non-zero
    status code.

    :param file_path: Path to the file to create.
    :param content: Content to write into the file.
    :param overwrite: Allow overwriting an existing file.
    """
    try:
        if file_path.exists() and not overwrite:
            raise CodeAgentError(
                f"File '{file_path}' already exists. Use --overwrite to replace."
            )
        _atomic_write(file_path, content)
        typer.echo(f"File written: {file_path}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Append text to an existing file.")
def append(
    file_path: Path = FILE_PATH_ARG_APPEND,
    content: str = typer.Option(..., help="Text to append to the file."),
) -> None:
    """Append ``content`` to ``file_path``.

    The function opens the file in append mode and writes the supplied
    content.  File locking is *not* required for the use-cases
    envisioned in this project.

    :param file_path: Path to the file to modify.
    :param content: Text to append to the file.
    :return: None
    """
    try:
        file_path.write_text(
            file_path.read_text(encoding="utf-8") + content,
            encoding="utf-8",
        )
        typer.echo(f"Appended to: {file_path}")
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(str(exc)) from exc


@app.command(help="Start an interactive chat session with the BergAgent.")
def chat(  # ruff: ignore [complex-structure]
    verbose: bool = typer.Option(
        False,  # ruff: ignore [boolean-positional-value-in-call]
        "--verbose",
        "-v",
        help="Show verbose streaming 'thinking' output from the agent.",
    ),
) -> None:
    """Start an interactive chat session with the BergAgent.

    :param verbose: Show verbose streaming 'thinking' output from the agent.
    :return: None
    """
    try:  # ruff: ignore [too-many-statements-in-try-clause]
        cfg = load_config()
        llm = create_llm(cfg)

        # Setup agent and tools
        agent, tools, root_dir = _setup_agent_and_tools(cfg, llm)

        # Set verbose flag on the agent so it can stream internal steps
        if hasattr(agent, "verbose"):
            agent.verbose = verbose

        _show_startup_info(root_dir, tools)

        from langchain.messages import HumanMessage, SystemMessage

        system_prompt = cfg.get("system_prompt", "")
        if system_prompt:
            system_prompt = system_prompt.format(root_dir=root_dir)
        conversation_messages: list[Any] = (
            [SystemMessage(content=system_prompt)] if system_prompt else []
        )
        thread_id = str(uuid.uuid4())
        # ``False`` until the first user message is sent; after that the graph's
        # checkpointer owns the conversation history, so we only ever send the
        # newest message (sending the full list would duplicate history).
        history_initialized = False

        # Main chat loop
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print("\nGoodbye!")
                break
            except KeyboardInterrupt:
                print("\n\n👋 Session ended by user. Goodbye!")
                break

            try:  # ruff: ignore [too-many-statements-in-try-clause]
                # Handle lifecycle and simple commands separately
                cont, cmd_result = _handle_command(
                    user_input, conversation_messages, tools
                )
                if not cont:
                    break
                if cmd_result is not None:
                    # command handled (like 'help' or 'tools')
                    conversation_messages = cmd_result
                    if not cmd_result:
                        # 'clear' was issued: drop the persisted graph
                        # history as well by starting a fresh thread.
                        thread_id = str(uuid.uuid4())
                        history_initialized = False
                    continue

                # Add user message and query the agent
                human_msg = HumanMessage(content=user_input)
                conversation_messages.append(human_msg)
                # Only the newest message is sent; the rest lives in the
                # graph's checkpointer under this thread_id.
                turn_messages = [human_msg]
                if not history_initialized and system_prompt:
                    turn_messages = [
                        SystemMessage(content=system_prompt),
                        human_msg,
                    ]
                history_initialized = True
                print("\n🤖 Thinking...")
                try:  # ruff: ignore [too-many-statements-in-try-clause]
                    response_text = _stream_agent_response(
                        agent=agent,
                        messages=turn_messages,
                        thread_id=thread_id,
                    )
                    print(f"\n🛠️  Agent response:\n{response_text}")
                    print("=" * 50 + "\n")
                except Exception as e:
                    print(f"\n❌ Error processing your request: {e!s}\n")
                    continue
            except Exception as e:
                print(f"\n❌ An unexpected error occurred: {e!s}\n")
                continue

    except Exception as e:
        print(f"\n❌ Failed to start chat: {e}", file=sys.stderr)
        sys.exit(1)


def _setup_agent_and_tools(
    cfg: dict[str, Any], llm: BaseChatModel
) -> tuple[Any, list[BaseTool], Path]:
    """Set up the agent and tools for the chat session.

    :param cfg: Configuration dictionary.
    :param llm: Language model instance.
    :return: Tuple of (agent, tools, root_dir)
    """
    root_dir = Path(cfg.get("root_dir", ".")).resolve()
    tools = create_default_tools(root_dir=str(root_dir), llm=llm)
    tools.extend(_load_mcp_tools(cfg))
    agent = build_agent(llm=llm, tools=tools)
    return agent, tools, root_dir


def _show_startup_info(root_dir: Path, tools: list[BaseTool]) -> None:
    """Show startup information for the chat session.

    :param root_dir: Root directory for the agent.
    :param tools: List of available tools.
    :return: None
    """
    print("\n" + "=" * 50)
    print("=== Berg Agents Chat ===")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print("Type 'help' to see available commands.\n")
    print(f"Root directory: {root_dir}")
    print(f"Available tools: {[t.name for t in tools]}")
    print("=" * 50 + "\n")


def _handle_command(
    user_input: str,
    conversation_messages: list[Any],
    tools: list,
    orchestrator: Any = None,
    config: dict[str, Any] | None = None,
) -> tuple[bool, list[Any] | None]:
    """Handle slash commands for the TUI. Returns (continue_session, messages or None).

    Slash commands (prefixed with /) provide access to system info and controls:
    /help, /agents, /models, /stats, /tools, /health, /history, /memory,
    /context, /settings, /plugins, /skills, /mcps, /orchestrate, /clear, /exit

    :param user_input: User input string.
    :param conversation_messages: Current conversation messages list.
    :param tools: List of available tools.
    :param orchestrator: Optional BergAgentsApp instance.
    :param config: Optional configuration dict.
    :return: Tuple of (continue_session, conversation_messages or None)
    """
    text = user_input.strip()

    # Exit commands
    if text.lower() in {"exit", "quit", "q", "/exit", "/quit"}:
        print("\nGoodbye!")
        return False, conversation_messages

    # Only treat as command if it starts with /
    if not text.startswith("/"):
        return True, conversation_messages

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        _cmd_help()
        return True, None

    if cmd == "/clear":
        print("Conversation history cleared.\n")
        return True, []

    if cmd == "/tools":
        _cmd_tools(tools)
        return True, None

    if cmd == "/agents":
        _cmd_agents(orchestrator)
        return True, None

    if cmd == "/models":
        _cmd_models(config)
        return True, None

    if cmd == "/stats":
        _cmd_stats(orchestrator)
        return True, None

    if cmd == "/health":
        _cmd_health(orchestrator, tools)
        return True, None

    if cmd == "/history":
        _cmd_history(conversation_messages)
        return True, None

    if cmd == "/memory":
        _cmd_memory()
        return True, None

    if cmd == "/context":
        _cmd_context(conversation_messages)
        return True, None

    if cmd == "/settings":
        _cmd_settings(config)
        return True, None

    if cmd == "/plugins":
        _cmd_plugins()
        return True, None

    if cmd == "/skills":
        _cmd_skills(config)
        return True, None

    if cmd == "/mcps":
        _cmd_mcps(config)
        return True, None

    if cmd == "/orchestrate":
        _cmd_orchestrate(args, orchestrator)
        return True, None

    if cmd == "/task":
        _cmd_task(args, orchestrator)
        return True, None

    if cmd == "/chat":
        print("You're already in chat mode. Just type your message.")
        return True, None

    print(f"Unknown command: {cmd}. Type /help for available commands.")
    return True, None


def _cmd_help() -> None:
    """Show available slash commands."""
    print("\n╔══════════════════════════════════════════════╗")
    print("║          BergAgents Slash Commands           ║")
    print("╠══════════════════════════════════════════════╣")
    print("║ /help          Show this help message        ║")
    print("║ /agents        List registered agents        ║")
    print("║ /models        Show available models         ║")
    print("║ /stats         Learning/outcome statistics   ║")
    print("║ /tools         List available tools          ║")
    print("║ /health        System health check           ║")
    print("║ /history       Show conversation history     ║")
    print("║ /memory        Show memory/context info      ║")
    print("║ /context       Show current context          ║")
    print("║ /settings      Show current settings         ║")
    print("║ /plugins       List loaded plugins           ║")
    print("║ /skills        List available skills         ║")
    print("║ /mcps          List MCP server status        ║")
    print("║ /orchestrate   Run task through orchestrator ║")
    print("║ /task          Same as /orchestrate          ║")
    print("║ /clear         Clear conversation history    ║")
    print("║ /exit          End the session               ║")
    print("╚══════════════════════════════════════════════╝")
    print("\nOr just type natural language to chat with the agent.\n")


def _cmd_tools(tools: list) -> None:
    """List available tools."""
    print("\n🔧 Available tools:")
    for tool in tools:
        desc = getattr(tool, "description", "").strip()
        print(f"  {tool.name:20} {desc[:60]}")
    print()


def _cmd_agents(orchestrator: Any) -> None:
    """List registered agents."""
    print("\n🤖 Registered agents:")
    if orchestrator is None:
        print("  Orchestrator not available.")
        return
    for agent in orchestrator.list_agents():
        caps = ", ".join(agent.get("capabilities", [])[:3])
        print(
            f"  {agent['name']:15} [{agent['preferred_model_tier']:6}] {agent['description']}"
        )
        if caps:
            print(f"  {'':15} Caps: {caps}")
    print()


def _cmd_models(config: dict[str, Any] | None) -> None:
    """Show available models."""
    print("\n📦 Models:")
    if config is None:
        print("  Config not available.")
        return
    providers = config.get("providers", {})
    for name, p in providers.items():
        models = p.get("models", {})
        print(f"  {name}:")
        for m in models:
            print(f"    - {m}")
    print()


def _cmd_stats(orchestrator: Any) -> None:
    """Show learning/outcome statistics."""
    print("\n📊 Learning Stats:")
    if orchestrator is None:
        print("  Orchestrator not available.")
        return
    stats = orchestrator.get_learning_stats()
    total = stats.get("total", 0)
    print(f"  Total tasks: {total}")
    by_model = stats.get("by_model", {})
    if by_model:
        print("  By Model:")
        for model, data in by_model.items():
            s = data.get("success", 0)
            f = data.get("failure", 0)
            rate = (s / (s + f) * 100) if (s + f) > 0 else 0
            print(f"    {model:20} {rate:5.0f}% ({s}/{s + f})")
    print()


def _cmd_health(orchestrator: Any, tools: list) -> None:
    """System health check."""
    print("\n🏥 Health Check:")
    print(f"  Tools loaded: {len(tools)}")
    if orchestrator:
        agents = orchestrator.list_agents()
        print(f"  Agents registered: {len(agents)}")
        print(
            f"  Learning enabled: {orchestrator.orchestrator.enable_learning}"
        )
    print("  Status: ✅ OK\n")


def _cmd_history(conversation_messages: list[Any]) -> None:
    """Show conversation history."""
    print("\n📜 Conversation History:")
    if not conversation_messages:
        print("  No messages yet.")
    else:
        for i, msg in enumerate(conversation_messages[-10:], 1):
            content = str(msg)[:80]
            print(f"  {i:3}. {content}")
    print()


def _cmd_memory() -> None:
    """Show memory/context info."""
    print("\n🧠 Memory:")
    print("  Session memory: Active (in-memory)")
    print("  Long-term: MemPalace integration pending")
    print()


def _cmd_context(conversation_messages: list[Any]) -> None:
    """Show current context."""
    print("\n📋 Context:")
    print(f"  Messages in history: {len(conversation_messages)}")
    print("  Context window: Dynamic (model-dependent)")
    print()


def _cmd_settings(config: dict[str, Any] | None) -> None:
    """Show current settings."""
    print("\n⚙️  Settings:")
    if config is None:
        print("  Config not available.")
        return
    print(f"  Provider: {config.get('provider', 'not set')}")
    print(f"  Model: {config.get('model', 'not set')}")
    print(f"  Root dir: {config.get('root_dir', 'not set')}")
    print()


def _cmd_plugins() -> None:
    """List loaded plugins."""
    print("\n🔌 Plugins:")
    print("  No plugins loaded (plugin system pending)")
    print()


def _cmd_skills(config: dict[str, Any] | None) -> None:
    """List available skills."""
    print("\n🎯 Skills:")
    if config is None:
        print("  Config not available.")
        return
    skills = config.get("skills", [])
    if skills:
        for s in skills:
            print(f"  - {s}")
    else:
        print("  No skills configured")
    print()


def _cmd_mcps(config: dict[str, Any] | None) -> None:
    """List MCP server status."""
    print("\n🔗 MCP Servers:")
    if config is None:
        print("  Config not available.")
        return
    mcps = config.get("mcp_servers", [])
    if mcps:
        for m in mcps:
            print(f"  - {m.get('name', 'unknown')}: {m.get('url', 'no url')}")
    else:
        print("  No MCP servers configured")
    print()


def _cmd_orchestrate(args: str, orchestrator: Any) -> None:
    """Run a task through the orchestrator."""
    if not args:
        print("Usage: /orchestrate <task description>")
        print("Example: /orchestrate refactor the auth module")
        return
    if orchestrator is None:
        print("Orchestrator not available.")
        return
    print(f"\n🤖 Executing: {args}")
    result = orchestrator.execute(args)
    status = result.get("status", "unknown")
    if status == "needs_human_review":
        print("⚠️  Human review required:")
        for reason in result.get("review_reasons", []):
            print(f"  - {reason}")
    elif status == "completed":
        print("✅ Task completed")
        plan = result.get("plan", [])
        if plan:
            print(f"  Subtasks: {len(plan)}")
    else:
        print(f"Status: {status}")
    print()


def _cmd_task(args: str, orchestrator: Any) -> None:
    """Alias for /orchestrate."""
    _cmd_orchestrate(args, orchestrator)


def _display_agent_response(
    response: Any, conversation_state: dict[str, Any]
) -> dict | Any:
    """Display the agent's response to the user.

    :param response: Response from the agent.
    :param conversation_state: Current conversation state.
    :return: Updated conversation state.
    """
    if isinstance(response, dict) and "messages" in response:
        print("\n" + "=" * 50)
        print("🛠️  Agent response:")
        messages = response["messages"]
        for msg in reversed(messages):
            if (
                isinstance(msg, (list, tuple))
                and len(msg) > 1
                and msg[0] in {"ai", "assistant"}
            ):
                print(msg[1])
                break
        print("=" * 50 + "\n")
        return response
    else:
        print("\n" + "=" * 50)
        print("🛠️  Agent response:")
        print(str(response))
        print("=" * 50 + "\n")
        return conversation_state


def main() -> None:  # pragma: no cover - thin wrapper
    """Entry point used by ``python -m berg_agents.cli``.

    This function initializes and runs the Typer CLI application.

    :return: None
    """
    app()


if __name__ == "__main__":
    # This allows the script to be run directly with `python -m berg_agents.cli`
    main()
