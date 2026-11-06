# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

"""BergAgents MCP (Model Context Protocol) client - framework-agnostic.

This module defines the interface for how BergAgents talks to external MCP servers.
It provides a framework-agnostic way to interact with MCP servers, without relying on any specific web framework or library.

What lives here
---------------
* **Naming helpers** - :data:`MCP_TOOL_PREFIX`, :data:`SERVER_SEP`,
  :func:`prefix_tool_name`, :func:`server_from_prefixed`,
  :func:`is_sensitive_server`, :func:`is_readonly_server`.
* **Transports** - :class:`McpTransport` (Protocol), :class:`StdioMcpTransport`
  (subprocess + newline-delimited JSON-RPC), :class:`HttpMcpTransport`
  (urllib + SSE listen thread; no third-party deps).
* **Client** - :class:`McpClient` and :class:`McpServerConfig` wrap a
  transport and present a one-line ``list_tools()`` / ``call_tool()``
  surface that returns :class:`~berg_agents.core.tool_spec.ToolSpec`
  objects the  loop can drop into its registry unchanged.

Design notes
------------
* **Stdio stderr is consumed on a background thread.**  The MCP servers
  the agent talks to (e.g. ``uvx mcp-server-github``) routinely log
  progress on stderr; if nobody reads it the pipe fills and the
  subprocess blocks.  ``StdioMcpTransport.__init__`` therefore spawns a
  daemon thread that calls ``read_stderr_forever`` and discards the
  bytes (with optional logging).
* **HTTP responses are demultiplexed by ``id``.**  The server pushes
  results back over an SSE stream; the transport keeps a ``dict[int,
  Future[Mapping]]`` so that ``request()`` returns exactly the response
  for the request it just sent.
* **No third-party deps.**  ``urllib.request`` and ``urllib.error`` are
  the only stdlib modules used for HTTP; threads are stdlib too.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
import contextlib
from dataclasses import dataclass, field
import json
import logging
import queue
import re
import subprocess
import threading
import time
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from berg_agents.core.tool_spec import ToolParam, ToolSpec

# ---------------------------------------------------------------------------
# Naming convention (must match config/mcp.py byte-for-byte)
# ---------------------------------------------------------------------------

#: Prefix namespace for every MCP-sourced tool so names never collide with
#: built-in tools (``edit-file``, ``read-file`` ...) and are trivially
#: identifiable as external.
MCP_TOOL_PREFIX = "mcp"

#: Separator between the server name and the original tool name.
SERVER_SEP = "__"

#: Servers whose tools can mutate external state or persisted memory.  Every
#: tool from one of these servers is interrupted for explicit user
#: approval.
SENSITIVE_SERVERS: frozenset[str] = frozenset({"github", "memory"})

#: Servers that are strictly read-only and safe to call autonomously.
READONLY_SERVERS: frozenset[str] = frozenset({"codegraph", "context7"})

# Matches ``mcp_<server>__<tool>`` and captures the server segment.
_PREFIX_RE = re.compile(
    rf"^{re.escape(MCP_TOOL_PREFIX)}_(?P<server>[^_]+){re.escape(SERVER_SEP)}.*$"
)


def prefix_tool_name(server_name: str, tool_name: str) -> str:
    """Return the agent-facing name for an MCP tool.

    :param server_name: MCP server key (e.g. ``"github"``).
    :param tool_name: Original tool name advertised by the server.
    :return: ``"mcp_<server>__<tool>"``.
    """
    return f"{MCP_TOOL_PREFIX}_{server_name}{SERVER_SEP}{tool_name}"


def server_from_prefixed(tool_name: str) -> str | None:
    """Extract the originating server name from a prefixed tool name.

    :param tool_name: A tool name, possibly prefixed.
    :return: The server name, or ``None`` when the name is not MCP-prefixed.
    """
    match = _PREFIX_RE.match(tool_name)
    return match.group("server") if match else None


def is_sensitive_server(
    server_name: str, enabled_servers: frozenset[str] | None = None
) -> bool:
    """Return ``True`` if *server_name* is sensitive (approval-required).

    When *enabled_servers* is provided (from loaded MCP server configuration),
    a server not in the enabled set is treated as not sensitive.

    :param server_name: MCP server key.
    :param enabled_servers: Optional set of server names that are configured
        and enabled. When provided, classification respects configuration.
    :return: Whether every tool from this server must be approved by a user.
    """
    if enabled_servers is not None and server_name not in enabled_servers:
        return False
    return server_name in SENSITIVE_SERVERS


def is_readonly_server(
    server_name: str, enabled_servers: frozenset[str] | None = None
) -> bool:
    """Return ``True`` if *server_name* is read-only (autonomous).

    When *enabled_servers* is provided (from loaded MCP server configuration file in .berg-agents directory),
    a server not in the enabled set is treated as not read-only.

    :param server_name: MCP server key.
    :param enabled_servers: Optional set of server names that are configured
        and enabled. When provided, classification respects configuration file in .berg-agents directory.
    :return: Whether every tool from this server is safe to call without
        user approval.
    """
    if enabled_servers is not None and server_name not in enabled_servers:
        return False
    return server_name in READONLY_SERVERS


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpError(RuntimeError):
    """Raised when an MCP request fails or returns an error payload.

    Carries the optional JSON-RPC ``code`` (when the server returned one)
    and the raw ``data`` payload so callers can decide whether to retry
    or surface the error to the user.

    :param code: JSON-RPC error code, or ``None`` for transport errors.
    :param data: Optional JSON-RPC ``data`` payload (any JSON-serializable
        object).
    """

    def __init__(
        self, message: str, *, code: int | None = None, data: Any = None
    ) -> None:
        """Store *message* and the optional JSON-RPC ``code`` / ``data``."""
        super().__init__(message)
        self.code = code
        self.data = data


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------


class McpTransport(Protocol):
    """One connection to one MCP server.

    :class:`McpTransport` implementations are the only thing that knows
    about bytes on a wire.  :class:`McpClient` consumes them and never
    sees a socket.
    """

    def request(
        self, method: str, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        """Send one JSON-RPC request and return the JSON-RPC response.

        :param method: JSON-RPC method name (``initialize``,
            ``tools/list``, ``tools/call``, ...).
        :param params: JSON-RPC ``params`` object (``None`` if absent).
        :return: The full JSON-RPC response payload (``result`` and/or
            ``error``).
        :raises McpError: If the request fails at the wire level or the
            server returned a JSON-RPC ``error`` object.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the transport (subprocess, socket)."""
        ...


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------


@dataclass
class StdioMcpTransport:
    """Newline-delimited JSON-RPC over a subprocess's stdin/stdout.

    :var command: Executable to launch (e.g. ``["uvx",
        "mcp-server-github"]``).  If the executable is on ``$PATH`` the
        plain name is fine; absolute paths also work.
    :var env: Optional environment overrides; merged with
        :data:`os.environ`.
    :var timeout_s: How long to wait for a single response before
        raising :class:`McpError`.
    :var logger: Optional logger for stderr noise; defaults to a
        module-level logger with level ``WARNING``.

    Stderr is read on a background daemon thread so the subprocess
    never blocks on a full pipe.
    """

    command: Sequence[str]
    env: Mapping[str, str] | None = None
    timeout_s: float = 30.0
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("berg_agents.core.mcp.stdio")
    )

    _proc: subprocess.Popen[bytes] | None = field(init=False, default=None)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _next_id: int = field(init=False, default=1)
    _stderr_thread: threading.Thread | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Spawn the subprocess and the stderr drainer thread."""
        import os

        merged_env: dict[str, str] = dict(os.environ)
        if self.env is not None:
            merged_env.update(self.env)
        try:
            self._proc = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]
                list(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
            )
        except OSError as exc:
            raise McpError(
                f"failed to spawn MCP subprocess {self.command!r}: {exc}"
            ) from exc
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"mcp-stderr-{self.command[0] if self.command else 'proc'}",
            daemon=True,
        )
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        """Read stderr forever, logging each line at DEBUG."""
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for raw in iter(self._proc.stderr.readline, b""):
                line = raw.decode(encoding="utf-8", errors="replace").rstrip()
                if not line:
                    continue
                self.logger.warning("mcp stderr: %s", line)
        except Exception as exc:  # ruff: ignore[blind-except] - drainer never raises
            self.logger.debug("mcp stderr drainer exited: %s", exc)

    def request(
        self, method: str, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        """Send a JSON-RPC request and return the response.

        :raises McpError: If the subprocess died, the response timed out,
            or the server returned a JSON-RPC ``error`` object.
        """
        if (
            self._proc is None
            or self._proc.stdin is None
            or self._proc.stdout is None
        ):
            raise McpError("stdio transport is not open")
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = dict(params)
            encoded = (json.dumps(payload) + "\n").encode("utf-8")
            try:
                self._proc.stdin.write(encoded)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise McpError(
                    f"failed to write to MCP subprocess: {exc}"
                ) from exc
            line = self._read_response_line()
        return self._parse_response(line, request_id)

    def _read_response_line(self) -> bytes:
        """Block on the subprocess's stdout until one JSON-RPC line arrives."""
        if self._proc is None or self._proc.stdout is None:
            raise McpError("stdio transport is not open")
        deadline = time.monotonic() + self.timeout_s
        while True:
            if self._proc.poll() is not None:
                raise McpError(
                    f"MCP subprocess exited with code {self._proc.returncode}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(
                    f"MCP request timed out after {self.timeout_s:.1f}s"
                )
            line = self._proc.stdout.readline()
            if not line:
                # EOF - server closed stdout
                raise McpError("MCP subprocess closed stdout unexpectedly")
            line = line.strip()
            if line:
                return line

    @staticmethod
    def _parse_response(line: bytes, request_id: int) -> Mapping[str, Any]:
        """Decode one JSON-RPC line and route to the right caller."""
        try:
            payload = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise McpError(f"MCP returned non-JSON line: {line!r}") from exc
        if not isinstance(payload, Mapping):
            raise McpError(f"MCP response is not a JSON object: {payload!r}")
        if payload.get("id") != request_id:
            raise McpError(
                f"MCP response id {payload.get('id')!r} does not match "
                f"request id {request_id!r}"
            )
        if "error" in payload:
            err = payload["error"]
            code = err.get("code") if isinstance(err, Mapping) else None
            data = err.get("data") if isinstance(err, Mapping) else None
            message = (
                err.get("message") if isinstance(err, Mapping) else str(err)
            )
            raise McpError(
                f"MCP error ({code}): {message}", code=code, data=data
            )
        return payload

    def close(self) -> None:
        """Terminate the subprocess and join the stderr drainer."""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                with contextlib.suppress(OSError):
                    proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
        except Exception as exc:  # ruff: ignore[blind-except]
            self.logger.debug("error closing stdio transport: %s", exc)


# ---------------------------------------------------------------------------
# HTTP transport (streamable-HTTP / SSE)
# ---------------------------------------------------------------------------


@dataclass
class HttpMcpTransport:
    """Streamable-HTTP JSON-RPC client built on :mod:`urllib` + threads.

    :param endpoint: Full URL of the MCP server's JSON-RPC endpoint
        (e.g. ``"http://127.0.0.1:8765/mcp"``).
    :param headers: Optional extra HTTP headers (e.g. auth tokens).
    :param listen_url: Optional URL of the SSE listen stream.  When
        ``None`` the transport sends one ``POST`` per request and
        expects the response in the POST body - that is the common case
        for ``mcp-streamablehttp``.  When supplied the transport opens
        a long-lived ``GET`` for server-pushed messages.
    :param timeout_s: Per-request HTTP timeout.
    :param sse_queue: Pre-built queue (used in tests).  When ``None``
        the transport creates its own.

    The transport holds a background thread that reads the SSE stream
    and demultiplexes events by JSON-RPC ``id`` into a
    ``dict[int, Future[Mapping]]``.  The main thread's ``request()`` call
    blocks on its own future.
    """

    endpoint: str
    headers: Mapping[str, str] = field(default_factory=dict)
    listen_url: str | None = None
    timeout_s: float = 30.0
    sse_queue: queue.Queue[Mapping[str, Any]] | None = None

    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _next_id: int = field(init=False, default=1)
    _pending: dict[int, threading.Event] = field(
        init=False, default_factory=dict
    )
    _responses: dict[int, Mapping[str, Any]] = field(
        init=False, default_factory=dict
    )
    _listen_thread: threading.Thread | None = field(init=False, default=None)
    _closed: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        """Start the SSE listen thread if a ``listen_url`` was provided."""
        if self.sse_queue is None:
            self.sse_queue = queue.Queue()
        if self.listen_url is not None:
            self._listen_thread = threading.Thread(
                target=self._sse_listen, name="mcp-http-sse", daemon=True
            )
            self._listen_thread.start()

    def request(
        self, method: str, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        """Send a JSON-RPC request and return the response.

        :raises McpError: If the HTTP POST fails or the response is not
            valid JSON-RPC.
        """
        if self._closed:
            raise McpError("http transport is closed")
        with self._lock:
            if self._closed:
                raise McpError("http transport is closed")
            request_id = self._next_id
            self._next_id += 1
            event = threading.Event()
            self._pending[request_id] = event
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = dict(params)
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(self.headers)
        req = urllib_request.Request(  # ruff: ignore[suspicious-url-open-usage]
            self.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_s) as resp:  # ruff: ignore[suspicious-url-open-usage]
                raw = resp.read()
        except urllib_error.URLError as exc:
            self._drop(request_id)
            raise McpError(f"MCP HTTP request failed: {exc}") from exc
        except OSError as exc:
            self._drop(request_id)
            raise McpError(f"MCP HTTP request failed: {exc}") from exc
        # The POST may itself carry the response (synchronous HTTP).
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._drop(request_id)
            raise McpError(f"MCP HTTP returned non-JSON: {raw!r}") from exc
        if not isinstance(parsed, Mapping):
            self._drop(request_id)
            raise McpError(
                f"MCP HTTP response is not a JSON object: {parsed!r}"
            )
        # If the response carries our id, deliver it directly.
        if parsed.get("id") == request_id:
            self._drop(request_id)
            return self._check_error(parsed)
        # Otherwise wait for the SSE thread to deliver it.
        return self._await_response(request_id)

    def _sse_listen(self) -> None:
        """Drain the SSE stream and route events to pending requests."""
        if self.listen_url is None or self.sse_queue is None:
            return
        req = urllib_request.Request(  # ruff: ignore[suspicious-url-open-usage]
            self.listen_url,
            headers={"Accept": "text/event-stream", **self.headers},
            method="GET",
        )
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            with urllib_request.urlopen(req, timeout=None) as resp:  # ruff: ignore[suspicious-url-open-usage]
                event_type = "message"
                data_lines: list[str] = []
                for raw in iter(resp.readline, b""):
                    if self._closed:
                        return
                    line = (
                        raw
                        .decode("utf-8", errors="replace")
                        .rstrip("\n")
                        .rstrip("\r")
                    )
                    if not line:
                        if data_lines:
                            self._handle_sse_event(
                                event_type, "\n".join(data_lines)
                            )
                            event_type = "message"
                            data_lines = []
                        continue
                    if line.startswith(":"):
                        continue  # SSE comment
                    if line.startswith("event:"):
                        event_type = line[len("event:") :].strip()
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[len("data:") :].lstrip())
        except Exception as exc:  # ruff: ignore[blind-except]
            if not self._closed:
                logging.getLogger("berg_agents.core.mcp.http").debug(
                    "SSE listen thread exited: %s", exc
                )

    def _handle_sse_event(self, event_type: str, data: str) -> None:
        """Parse one SSE ``data:`` payload and route it to a request."""
        if event_type not in {"message", "response", ""}:
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, Mapping):
            return
        request_id = payload.get("id")
        if not isinstance(request_id, int):
            return
        with self._lock:
            event = self._pending.get(request_id)
            if event is None:
                return
            self._responses[request_id] = payload
        event.set()

    def _await_response(self, request_id: int) -> Mapping[str, Any]:
        """Block on the SSE-driven response for *request_id*."""
        with self._lock:
            event = self._pending.get(request_id)
        if event is None:
            raise McpError("MCP request id vanished from pending map")
        if not event.wait(timeout=self.timeout_s):
            self._drop(request_id)
            raise McpError(
                f"MCP HTTP request timed out after {self.timeout_s:.1f}s"
            )
        with self._lock:
            payload = self._responses.pop(request_id, None)
        if payload is None:
            raise McpError("MCP HTTP response missing after event")
        return self._check_error(payload)

    def _drop(self, request_id: int) -> None:
        """Remove bookkeeping for a completed (or failed) request."""
        with self._lock:
            self._pending.pop(request_id, None)
            self._responses.pop(request_id, None)

    @staticmethod
    def _check_error(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Raise :class:`McpError` if the payload carries one."""
        if "error" in payload:
            err = payload["error"]
            code = err.get("code") if isinstance(err, Mapping) else None
            data = err.get("data") if isinstance(err, Mapping) else None
            message = (
                err.get("message") if isinstance(err, Mapping) else str(err)
            )
            raise McpError(
                f"MCP error ({code}): {message}", code=code, data=data
            )
        return payload

    def close(self) -> None:
        """Mark the transport closed; the SSE thread will exit on its own."""
        self._closed = True
        with self._lock:
            for event in self._pending.values():
                event.set()


# ---------------------------------------------------------------------------
# Server config + client
# ---------------------------------------------------------------------------


@dataclass
class McpServerConfig:
    """Static description of one MCP server.

    :var name: Server key (e.g. ``"github"``).
    :var transport: An open :class:`McpTransport`.  Ownership of the
        transport's lifetime transfers to the client; ``client.close()``
        calls ``transport.close()`` for the caller.
    :var sensitive: When ``True`` the loop must gate every tool call
        from this server through HITL.  Defaults to whatever
        :func:`is_sensitive_server` says about *name*.
    :var readonly: When ``True`` tools from this server never need
        HITL.  Defaults to :func:`is_readonly_server`(*name*).
    """

    name: str
    transport: McpTransport
    sensitive: bool | None = None
    readonly: bool | None = None

    def resolved_sensitive(self) -> bool:
        """Return the effective sensitive flag (default derived from *name*)."""
        if self.sensitive is not None:
            return self.sensitive
        return is_sensitive_server(self.name)

    def resolved_readonly(self) -> bool:
        """Return the effective read-only flag (default derived from *name*)."""
        if self.readonly is not None:
            return self.readonly
        return is_readonly_server(self.name)


@dataclass
class McpClient:
    """One connection to one MCP server.

    The lifecycle is ``initialize`` (handshake) → ``tools/list`` (cache)
    → repeated ``tools/call`` (one per loop step).  Errors at any
    stage are surfaced as :class:`McpError`.  The client is single-use
    per server: open a new one if you need a fresh handshake.

    :var config: :class:`McpServerConfig` describing the server.
    """

    config: McpServerConfig
    _tools: tuple[ToolSpec, ...] = field(init=False, default=())
    _initialized: bool = field(init=False, default=False)

    def initialize(self) -> Mapping[str, Any]:
        """Send the MCP ``initialize`` handshake.

        :return: The server's ``result`` payload (capabilities, server
            info, protocol version).
        :raises McpError: If the handshake fails.
        """
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "berg-agents", "version": "0.2.0"}}
        response = self.config.transport.request("initialize", params)
        self._initialized = True
        return response.get("result", {})

    def list_tools(self) -> Sequence[ToolSpec]:
        """Return the cached :class:`ToolSpec` list for this server.

        Calls ``tools/list`` on first invocation, then returns the
        cached tuple.  Tool names are prefixed with ``mcp_<server>__``
        so the loop can dispatch them by name.

        :return: The cached :class:`ToolSpec` tuple, in server order.
        :raises McpError: If the server returns a malformed payload.
        """
        if self._tools:
            return self._tools
        if not self._initialized:
            self.initialize()
        response = self.config.transport.request("tools/list", None)
        result = response.get("result", {})
        raw_tools = (
            result.get("tools", []) if isinstance(result, Mapping) else []
        )
        if not isinstance(raw_tools, list):
            raise McpError(
                f"MCP tools/list returned non-list 'tools' field: {raw_tools!r}"
            )
        tools: list[ToolSpec] = []
        for entry in raw_tools:
            if not isinstance(entry, Mapping):
                raise McpError(
                    f"MCP tool entry is not a JSON object: {entry!r}"
                )
            tools.append(self._build_spec(entry))
        self._tools = tuple(tools)
        return self._tools

    def _build_spec(self, entry: Mapping[str, Any]) -> ToolSpec:
        """Translate one MCP ``tools/list`` entry into a :class:`ToolSpec`."""
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise McpError(f"MCP tool entry missing 'name': {entry!r}")
        description = entry.get("description", "")
        if not isinstance(description, str):
            description = str(description)
        raw_schema = entry.get("inputSchema", {"type": "object"})
        if not isinstance(raw_schema, Mapping):
            raw_schema = {"type": "object"}
        params = _params_from_schema(raw_schema)
        prefixed_name = prefix_tool_name(self.config.name, name)
        tags = ("mcp", self.config.name)
        if self.config.resolved_readonly():
            tags = (*tags, "read-only")
        if self.config.resolved_sensitive():
            tags = (*tags, "sensitive")
        return ToolSpec(
            name=prefixed_name,
            description=description,
            params=params,
            execute=self._make_executor(name),
            tags=tags,
        )

    def _make_executor(self, original_name: str) -> Callable[..., Any]:
        """Return a closure that dispatches ``tools/call`` to the server.

        :param original_name: The un-prefixed MCP tool name (the
            ``execute`` closure must use the original name in the JSON-RPC
            payload, not the prefixed one).
        """

        def _execute(**kwargs: Any) -> Any:
            response = self.config.transport.request(
                "tools/call", {"name": original_name, "arguments": dict(kwargs)}
            )
            result = response.get("result", {})
            if isinstance(result, Mapping):
                content = result.get("content", result)
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, Mapping) and "text" in first:
                        return first.get("text")
                if "isError" in result and result.get("isError"):
                    raise McpError(
                        f"MCP tool {original_name!r} returned an error: "
                        f"{result!r}"
                    )
                return content
            return result

        _execute.__name__ = f"mcp_{self.config.name}_{original_name}"
        return _execute

    def close(self) -> None:
        """Release the underlying transport."""
        self.config.transport.close()


# ---------------------------------------------------------------------------
# JSON-Schema -> ToolParam conversion
# ---------------------------------------------------------------------------


def _params_from_schema(schema: Mapping[str, Any]) -> tuple[ToolParam, ...]:
    """Translate a JSON-Schema ``object`` into a tuple of :class:`ToolParam`.

    Only the subset MCP servers actually use is supported: ``type``,
    ``description``, ``enum``, and ``default``.  Unknown properties
    (``$ref``, ``oneOf``, ...) are silently dropped - the model only
    needs enough info to call the tool correctly.
    """
    properties = schema.get("properties", {})
    required_list = schema.get("required", [])
    if not isinstance(properties, Mapping):
        return ()
    if not isinstance(required_list, list):
        required_list = []
    required = {name for name in required_list if isinstance(name, str)}
    params: list[ToolParam] = []
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, Mapping):
            continue
        type_name = prop.get("type", "string")
        if not isinstance(type_name, str):
            type_name = "string"
        description = prop.get("description", "")
        if not isinstance(description, str):
            description = str(description)
        enum = prop.get("enum")
        default = prop.get("default")
        params.append(
            ToolParam(
                name=name,
                type=type_name,
                description=description,
                required=name in required,
                enum=enum,
                default=default,
            )
        )
    return tuple(params)


# ---------------------------------------------------------------------------
# Convenience: drive many clients
# ---------------------------------------------------------------------------


def iter_servers_to_clients(
    configs: Iterable[McpServerConfig],
) -> Iterator[McpClient]:
    """Yield one :class:`McpClient` per :class:`McpServerConfig`.

    Each client is initialized eagerly (``initialize`` + ``tools/list``)
    so the caller can iterate the union of their tool caches in a
    single pass.  Clients remain open until the caller calls
    :meth:`McpClient.close` (or :func:`close_all`).
    """
    for config in configs:
        client = McpClient(config=config)
        client.initialize()
        client.list_tools()
        yield client


def close_all(clients: Iterable[McpClient]) -> None:
    """Close a sequence of :class:`McpClient` instances.

    :param clients: Any iterable of clients (closed in iteration order).
    """
    logger = logging.getLogger("berg_agents.core.mcp")
    for client in clients:
        with contextlib.suppress(Exception):  # ruff: ignore[blind-except]
            client.close()
        logger.debug("closed MCP client %s", getattr(client, "config", None))


# ---------------------------------------------------------------------------
# Server configuration loading and client construction
# ---------------------------------------------------------------------------


def load_mcp_server_configs(
    cfg: dict[str, Any] | None = None,
) -> list[McpServerConfig]:
    """Load MCP server configurations from settings into ``McpServerConfig`` list.

    Reads ``mcp_servers`` from *cfg* (or from application settings when
    *cfg* is ``None``). The value is either a JSON-encoded list of server
    configuration dicts or a path to a JSON file containing that list. Each entry
    is validated and converted to a :class:`McpServerConfig`. The ``enabled``
    flag (when present) populates the enabled set used by the ``enabled_servers``
    parameter of :func:`is_sensitive_server` and :func:`is_readonly_server`
    so MCP enabled flags participate in sensitive/read-only classification.

    :param cfg: Optional configuration dict override.
    :return: List of :class:`McpServerConfig`.
    """
    if cfg is None:
        from berg_agents.config.settings import get_settings

        cfg = get_settings().model_dump()

    raw = cfg.get("mcp_servers") if cfg else None
    if not raw:
        return []

    import json as _json

    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            server_list = _json.loads(raw)
        except _json.JSONDecodeError:
            return []
    elif isinstance(raw, str) and raw.endswith(".json"):
        from pathlib import Path as _Path

        path = _Path(raw)
        if not path.is_absolute():
            from berg_agents.config.settings import PROJECT_ROOT

            path = PROJECT_ROOT / path
        if path.is_file():
            try:
                with path.open(encoding="utf-8") as fp:
                    server_list = _json.load(fp)
            except (OSError, _json.JSONDecodeError):
                return []
        else:
            return []
    else:
        return []

    if not isinstance(server_list, list):
        return []

    configs: list[McpServerConfig] = []
    enabled_servers: set[str] = set()
    for entry in server_list:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("id")
        if not name or not isinstance(name, str):
            continue
        if entry.get("enabled", True):
            enabled_servers.add(name)
        transport: McpTransport
        if entry.get("type") == "stdio":
            transport = StdioMcpTransport(
                command=entry.get("command", []), env=entry.get("env")
            )
        else:
            transport = HttpMcpTransport(
                endpoint=entry.get("url", ""), headers=entry.get("headers")
            )
        configs.append(
            McpServerConfig(
                name=name,
                transport=transport,
                sensitive=entry.get("sensitive"),
                readonly=entry.get("readonly"),
            )
        )
    return configs


__all__ = [
    "MCP_TOOL_PREFIX",
    "READONLY_SERVERS",
    "SENSITIVE_SERVERS",
    "SERVER_SEP",
    "HttpMcpTransport",
    "McpClient",
    "McpError",
    "McpServerConfig",
    "McpTransport",
    "StdioMcpTransport",
    "close_all",
    "is_readonly_server",
    "is_sensitive_server",
    "iter_servers_to_clients",
    "load_mcp_server_configs",
    "prefix_tool_name",
    "server_from_prefixed"]
