"""A specialist as its own run — phase S1.

The orchestrator starts a specialist as a **run of its own** and holds the run
id. That is the whole point of this module, and it is what the subagent shape
could not do: a child nested in the parent's tool call dies when the parent's
pass ends, whereas a run with its own id keeps working, keeps a record, and can
be read, steered or stopped afterwards.

One function per operation, each on a run id:

* :func:`start_specialist` — start a turn for a named specialist.
* :func:`specialist_state` — what it is doing right now, from its durable record.
* :func:`specialist_report` — what it did, once it is done.

The three read cases are distinguished deliberately, because they are different
states and Stop acts on them differently (decisions-log, 2026-11-11):

* ``waiting`` — parked on a gate; its pass has ended, so its status is
  ``completed`` while it still holds pending calls;
* ``working`` — a pass is actually executing;
* ``pending`` — started, not yet claimed by the worker.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any


#: The specialists berg registers. Read from the harness rather than restated,
#: so a new agent in the registry is startable without touching this module.
def known_specialists() -> list[str]:
    """The names a specialist can be started for.

    :return: Registered agent names, from berg's own registry.
    """
    from berg_agents.core.harness import Harness

    harness = Harness(enable_inference=False)
    return [str(info.get("name")) for info in harness.get_agent_info()]


def start_specialist(
    agent_name: str,
    task: str,
    *,
    session_id: str | None = None,
    root_dir: str = ".",
    model_id: str | None = None,
) -> dict[str, Any]:
    """Start a specialist's turn as a run of its own.

    The run is started exactly as a chat turn is — the same gated workflow, the
    same wire, the same durable record — with the specialist as the active
    agent. Nothing here is a new runtime; it is the same host, addressed by name.

    :param agent_name: Which specialist (``implementation``, ``planner``, …).
    :param task: What it should do, in the user's words.
    :param session_id: The session it belongs to, when it has one.
    :param root_dir: Workspace root its tools bind to.
    :param model_id: Model override; the specialist's tier when ``None``.
    :return: ``{"run_id", "token", "agent_name"}`` — what the orchestrator holds.
    :raises ValueError: When the name is not a registered specialist.
    """
    if agent_name not in known_specialists():
        raise ValueError(
            f"{agent_name!r} is not a registered specialist; "
            f"known: {sorted(known_specialists())}"
        )

    # Started THROUGH berg's own intake over HTTP, not by calling
    # ``workflow.start`` here. That distinction is not style: ``workflow.start``
    # uses whatever queue the importing process has configured, so a caller that
    # is not the server enqueues into a process that then exits and the run sits
    # ``pending`` forever (observed 2026-11-11, queue empty, status pending). The
    # intake is the one door the whole port was proven through.
    token = secrets.token_hex(6)
    payload: dict[str, Any] = {
        "prompt": task,
        "token": token,
        "agent": agent_name,
        "root_dir": root_dir}
    if session_id:
        payload["session_id"] = session_id
    if model_id:
        payload["model"] = model_id
    started = _post_json("/api/workflow/chat", payload)
    return {
        "run_id": str(started.get("run_id", "")),
        "token": str(started.get("token", token)),
        "agent_name": agent_name}


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to berg's own server and return its JSON answer.

    :param path: Endpoint path, e.g. ``/api/workflow/chat``.
    :param payload: JSON body.
    :return: The decoded response.
    :raises RuntimeError: When berg's server cannot be reached.
    """
    import json
    import os
    import urllib.request

    base = os.getenv("BERG_SELF_URL", "http://127.0.0.1:8001")
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # ruff: ignore[suspicious-url-open-usage]
            raw = response.read().decode()
    except Exception as exc:  # ruff: ignore[blind-except] - re-raised with context
        raise RuntimeError(
            f"berg's server is unreachable at {base}: {exc}"
        ) from exc
    return json.loads(raw) if raw.strip() else {}


def approve_specialist(
    run_id: str,
    *,
    approved: bool,
    reason: str | None = None,
    steer: str | None = None,
) -> dict[str, Any]:
    """Synchronous door to :func:`approve_specialist_async`.

    Kept because the obvious caller — a script, a CLI, a tool body that is not
    itself awaiting — has no loop to hand. Anything already inside an event loop
    must await the async form: nesting ``asyncio.run`` inside a running loop
    breaks anyio's cancel scopes ("Attempted to exit cancel scope in a different
    task than it was entered in"), which is how that wrapper was found.

    :param run_id: The parked specialist run.
    :param approved: Whether the user allowed the call.
    :param reason: Why not, when rejected.
    :param steer: New instruction that supersedes what it was about to do.
    :return: ``{"run_id", "token", "agent_name"}`` for the resumed run.
    """
    return asyncio.run(
        approve_specialist_async(
            run_id, approved=approved, reason=reason, steer=steer
        )
    )


async def specialist_state_async(run_id: str) -> dict[str, Any]:
    """What a specialist run is doing, read from its durable record.

    :param run_id: The specialist's run id.
    :return: ``{"state": "waiting" | "working" | "pending" | "done", ...}`` with
        the pending calls when it is waiting on a gate.
    """
    from berg_agents.workflow.routes import _parked_pass

    parked = _parked_pass(run_id)
    status = await _status_of(run_id)

    if parked:
        # A parked run's pass has ENDED, so its status is ``completed`` while it
        # still holds calls awaiting a decision. That combination is the only
        # thing that means "waiting", and it is why status alone cannot say.
        return {
            "state": "waiting",
            "status": status,
            "pending": parked["pending"]}
    if status in {"completed", "failed", "cancelled", "terminated"}:
        return {"state": "done", "status": status, "pending": []}
    if status == "pending":
        return {"state": "pending", "status": status, "pending": []}
    return {"state": "working", "status": status, "pending": []}


def specialist_state(run_id: str) -> dict[str, Any]:
    """Synchronous door to :func:`specialist_state_async`.

    :param run_id: The specialist's run id.
    :return: Its state, as the async form reports it.
    """
    return asyncio.run(specialist_state_async(run_id))


async def approve_specialist_async(
    run_id: str,
    *,
    approved: bool,
    reason: str | None = None,
    steer: str | None = None,
) -> dict[str, Any]:
    """Answer a specialist's gated call, by re-driving its run.

    Goes through berg's **approval endpoint**, not the in-process helper. That is
    not a convenience: ``workflow.start`` uses whatever queue the *calling*
    process has configured, so a caller outside the server enqueues into a
    process that then exits — the run sits ``pending`` with an empty broker
    (observed twice). The endpoint is where the server does it, with its queue
    already pointed at itself, so every caller takes the one working path.

    :param run_id: The specialist run currently parked on a gate.
    :param approved: Whether the user allowed the call.
    :param reason: Why not, when rejected.
    :param steer: New instruction that supersedes what it was about to do.
    :return: ``{"run_id", "token", "agent_name"}`` for the resumed run.
    :raises RuntimeError: When berg's server cannot be reached.
    """
    payload: dict[str, Any] = {
        "decision": "approved" if approved else "rejected"}
    if reason:
        payload["reason"] = reason
    if steer:
        payload["steer"] = steer
    served = await asyncio.to_thread(
        _post_json, f"/api/workflow/chat/{run_id}/approval", payload
    )
    if not served.get("run_id"):
        raise RuntimeError(
            f"berg's server did not resume {run_id!r}: {served}"
        )
    return {
        "run_id": str(served["run_id"]),
        "token": str(served.get("token") or ""),
        "agent_name": str(served.get("agent_name") or "")}


async def _status_of(run_id: str) -> str:
    """A run's status string, or ``"unknown"`` when it cannot be read.

    :param run_id: The run to read.
    :return: Its status, or ``"unknown"``.
    """
    from vercel import workflow

    try:
        return str(await workflow.Run(run_id).status())
    except Exception:  # ruff: ignore[blind-except] - an unreadable run is unknown
        return "unknown"


async def specialist_report_async(run_id: str) -> dict[str, Any]:
    """What a specialist did, as an orchestrator needs to hear it.

    The run's raw outcome is the *pass record* — history, frames, pending calls —
    which is right for the host and wrong for a report. What a caller asks is
    "what did it say, and what did it touch", so this reads those out of the
    durable record instead: the assistant's own text, and the tool calls it made
    with their outcomes. The raw record stays available under ``record`` for
    anything that wants it.

    :param run_id: The specialist's run id.
    :return: Its state, what it said, what it did, and the frame count.
    """
    state = await specialist_state_async(run_id)
    report: dict[str, Any] = {"run_id": run_id, **state}
    if state["state"] != "done":
        return report

    record = await _outcome_of(run_id)
    report["said"] = _said(record)
    report["did"] = _did(record)
    report["frames"] = len(await _transcript_of(run_id))
    report["record"] = record
    return report


def _said(record: Any) -> str:
    """The assistant's own final text from a run record.

    :param record: The run's outcome, or ``None``.
    :return: Its last assistant text, empty when there is none.
    """
    if not isinstance(record, dict):
        return ""
    said = ""
    for message in record.get("history") or []:
        if not isinstance(message, dict) or message.get("kind") != "response":
            continue
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("part_kind") == "text":
                text = str(part.get("content") or "").strip()
                if text:
                    said = text
    return said


def _did(record: Any) -> list[dict[str, Any]]:
    """The tool calls a run made, with what came back.

    :param record: The run's outcome, or ``None``.
    :return: One entry per call: ``{"tool", "args", "result"}``.
    """
    if not isinstance(record, dict):
        return []
    results: dict[str, str] = {}
    for message in record.get("history") or []:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("part_kind") != "tool-return":
                continue
            call_id = str(part.get("tool_call_id") or "")
            if call_id:
                results[call_id] = str(part.get("content") or "")

    did: list[dict[str, Any]] = []
    for message in record.get("history") or []:
        if not isinstance(message, dict) or message.get("kind") != "response":
            continue
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("part_kind") != "tool-call":
                continue
            call_id = str(part.get("tool_call_id") or "")
            did.append(
                {
                    "tool": str(part.get("tool_name") or ""),
                    "args": part.get("args"),
                    "result": results.get(call_id, "")}
            )
    return did


def specialist_report(run_id: str) -> dict[str, Any]:
    """Synchronous door to :func:`specialist_report_async`.

    :param run_id: The specialist's run id.
    :return: The report, as the async form builds it.
    """
    return asyncio.run(specialist_report_async(run_id))


async def _outcome_of(run_id: str) -> Any:
    """A finished run's return value, or ``None``.

    :param run_id: The run to read.
    :return: Its outcome, or ``None`` when it has none to give.
    """
    from vercel import workflow

    try:
        return await workflow.Run(run_id).return_value()
    except Exception:  # ruff: ignore[blind-except] - no outcome is not an error
        return None


async def _transcript_of(run_id: str) -> list[dict[str, Any]]:
    """A finished run's frames, decoded from its durable stream.

    :param run_id: The run to read.
    :return: Its frames, empty when the stream cannot be read.
    """
    from berg_agents.workflow.registry import Frame
    from vercel import workflow

    try:
        frames: list[dict[str, Any]] = []
        async for frame in workflow.Run(run_id).readable(type=Frame):
            frames.append(
                frame.model_dump()
                if hasattr(frame, "model_dump")
                else {"data": str(frame)}
            )
        return frames
    except Exception:  # ruff: ignore[blind-except] - a missing stream is empty
        return []
