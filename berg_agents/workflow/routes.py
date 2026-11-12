"""The two HTTP surfaces the workflow runtime needs, mounted on berg's router.

One route receives sends; the other is the consumer the SDK hands back, mounted
unchanged. The dispatcher joins them, settling each message by whether the
consumer accepted it.

What each side expects was read off the installed SDK rather than guessed
(``vercel-workflow==0.12.1``):

* a send is ``POST /api/v3/topic/{topic}`` with ``Authorization: Bearer <token>``,
  ``Vqs-Client-Ts`` and optional ``Vqs-Idempotency-Key`` /
  ``Vqs-Retention-Seconds`` / ``Vqs-Delay-Seconds``; the body is the
  transport-serialised payload, which for this runtime is the
  ``{payload, queueName, deploymentId}`` envelope its own ``queue()`` builds.
* the consumer reads headers ``x-vqs-queue-name``, ``x-vqs-message-id``,
  ``x-vqs-message-attempt`` and a **bare payload** body, wrapping the envelope
  itself. Passing it the stored envelope double-wraps it.

The consumer function lives in the SDK's internal module
(``vercel.workflow._internal.runtime``), which is not a published surface. berg
couples to it knowingly: it is the only place these primitives exist, and the
coupling is recorded so a version bump gets re-checked rather than discovered in
production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
import json
from pathlib import Path
from typing import Any

from berg_agents.workflow import queue as broker
from berg_agents.workflow.registry import point_queue_at_berg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

#: Below this the consumer accepted the delivery; at or above it, the delivery
#: failed and must be retried rather than settled.
_HTTP_OK_MAX = 400


class _Delivery:
    """The request shape the SDK's consumer reads.

    ``url`` is a plain string, not a URL object: the SDK calls ``.decode()`` on
    it, and its health-check wrapper reads the path.
    """

    def __init__(self, url: str, headers: dict[str, str], body: bytes) -> None:
        self.url = url
        self.headers = headers
        self.method = "POST"
        self._body = body

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        yield self._body

    async def body(self) -> bytes:
        return self._body


def build_consumer() -> Any:
    """The SDK's own consumer handler, ready to mount.

    :return: The callable ``workflow_entrypoint`` returns. Imported lazily so a
        failed SDK import cannot break importing berg's routes.
    """
    # The only place these primitives exist, and not a published surface. The
    # coupling is recorded in decisions/decisions-log.md so a version bump is
    # re-checked rather than discovered in production.
    from berg_agents.workflow.registry import wf
    from vercel.workflow._internal.runtime import workflow_entrypoint  # ruff: ignore[import-private-name]

    return workflow_entrypoint(wf)


async def receive_delivery() -> int:
    """Claim and deliver every due message, settling each by outcome.

    A message whose worker died keeps its row with an expired lease, so this is
    where an interrupted run resumes — the behaviour that makes berg's queue
    durable rather than merely persistent.

    :return: How many messages were attempted.
    """
    from berg_agents.workflow.registry import _CONSUMER

    handled = 0
    for message in broker.claim_ready():
        await deliver(message, _CONSUMER)
        handled += 1
    return handled


async def deliver(message: dict, consumer: Any) -> bool:
    """Deliver one message to the SDK's consumer and settle it.

    :param message: A claimed queue message.
    :param consumer: The SDK's consumer callable.
    :return: Whether the consumer accepted it.
    """
    headers = {
        "x-vqs-queue-name": message["topic"],
        "x-vqs-message-id": message["message_id"],
        "x-vqs-message-attempt": str(message["attempts"])}
    body = bytes(message["payload"])
    # The consumer expects the bare payload and wraps the envelope itself, so
    # the stored envelope is unwrapped here exactly once. A body that is not
    # JSON, or is already bare, is handed over unchanged.
    with contextlib.suppress(Exception):
        body = json.dumps(json.loads(body)["payload"]).encode()
    request = _Delivery(
        f"http://127.0.0.1:8001{broker.QUEUE_API_PATH}/{message['topic']}",
        headers,
        body,
    )
    try:
        response = await consumer(request)
        ok = getattr(response, "status_code", 200) < _HTTP_OK_MAX
    except Exception as exc:  # a failed delivery is retried, never dropped
        print(
            f"[workflow-queue] consumer raised for {message['message_id'][:14]}: {exc}"
        )
        ok = False
    broker.settle(message["message_id"], done=ok)
    return ok


def _new_token() -> str:
    """A fresh hook/stream token for a run.

    The workflow body runs deterministically, so the token is minted here in the
    request path rather than inside the workflow.
    """
    import secrets

    return secrets.token_hex(6)


#: The devalue envelope's width for its little-endian payload length.
_LENGTH_BYTES = 4


#: The devalue envelope's width for its little-endian payload length.
_LENGTH_BYTES = 4


async def _resume_parked(
    run_id: str,
    parked: dict[str, Any],
    *,
    approved: bool,
    reason: str | None,
    steer: str | None = None,
) -> str:
    """Resume a parked run with its decision, and return the new run's id.

    One path, used by the approval route and by the orchestrator's
    ``approve_specialist``: a gate is answered by resuming (the parked pass has
    ended), so every caller has to do the same four things — collect any steer,
    turn the decision into plain data, start the next run, and hand its id back.

    :param run_id: The parked run being answered.
    :param parked: Its parked record, from ``_parked_pass``.
    :param approved: Whether the user allowed the calls.
    :param reason: Why not, when rejected.
    :param steer: A new instruction that supersedes the pending ones; when
        absent, the turn's stored steers are used.
    :return: The resumed run's id.
    """
    from berg_agents.workflow.gated_turn import gated_turn
    from vercel import workflow

    steer_text = (steer or "").strip()
    if not steer_text:
        # Read WITHOUT clearing: the resumed pass owns the store (``take_steers``
        # clears on read), and clearing here too would make delivery depend on
        # which of the two happened to run first.
        from berg_agents.workflow.steering import read_steers

        turn = _turn_token(run_id) or parked.get("token") or ""
        steers = read_steers(turn) if turn else []
        steer_text = " ".join(s for s in steers if s.strip()).strip()

    # Plain data across the boundary: a pydantic object cannot be serialised
    # into a step's arguments, so the run rebuilds DeferredToolResults itself.
    approvals = {
        call["tool_call_id"]: {
            "approved": approved,
            "reason": reason,
            "steer": steer_text or None}
        for call in parked["pending"]
    }
    run = await workflow.start(
        gated_turn,
        token=parked["token"],
        prompt=parked["prompt"],
        model_id=parked["model_id"],
        root_dir=parked["root_dir"],
        active_agent=parked["active_agent"],
        active_agent_description=parked["active_agent_description"],
        _decisions=approvals,
        _history=parked["history"],
    )
    return str(run.run_id)


def _turn_token(run_id: str) -> str | None:
    """The turn's token for a run, from the run's own stored input.

    A turn spans several runs (the parked one and each resumed one), and the
    token is the part that stays the same, so it is what a steer is filed
    under.

    :param run_id: Any run belonging to the turn.
    :return: The token, or ``None`` when the record cannot be read.
    """
    started = _decode_payload((_run_record(run_id) or {}).get("input"))
    if isinstance(started, list) and started and isinstance(started[0], dict):
        started = started[0]
    if isinstance(started, dict):
        token = started.get("token")
        if isinstance(token, str) and token:
            return token
    return None


def _decode_payload(raw: Any) -> Any:
    """Decode a stored payload with the runtime's own decoder.

    The runtime stores inputs, outputs and step results as format-prefixed,
    **compressed** payloads, and ``serialization.hydrate`` is its own decoder
    for them — so berg reads through it rather than parsing bytes by hand.
    The value also arrives JSON-wrapped as ``{"__type": "Uint8Array",
    "data": ...}`` when it comes from the event log, which is unwrapped first.

    :param raw: The stored value, in either shape.
    :return: The decoded value, or ``None`` when it cannot be read.
    """
    import base64

    if isinstance(raw, dict) and raw.get("__type") == "Uint8Array":
        try:
            raw = base64.urlsafe_b64decode(str(raw.get("data", "")) + "===")
        except Exception:  # ruff: ignore[blind-except] - unreadable stays None
            return None
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return None
    try:
        # The runtime owns this format; berg decodes through it rather than
        # re-implementing its compression and framing.
        from vercel.workflow._internal import serialization  # ruff: ignore[import-private-name]

        return serialization.hydrate(bytes(raw), what="a stored run payload")
    except Exception:  # ruff: ignore[blind-except] - an unreadable payload is not parked
        return None


def _parked_pass(run_id: str) -> dict[str, Any] | None:
    """What the run parked on, and the context to resume it with.

    The durable record holds all of it: the step's own outcome (which carries
    the pending calls) sits in the run's event log, and the run's inputs sit
    on the run itself. Reading both through the runtime's own files is what
    makes the answer key durable — the run id resolves it, wherever the
    process is.

    :param run_id: The run that parked on the gate.
    :return: The pending calls plus the context to resume with, or ``None``
        when that run holds no parked gate.
    """
    from berg_agents.workflow.registry import _workflow_data_dir

    events_dir = _workflow_data_dir() / Path("events") / run_id
    if not events_dir.is_dir():
        return None

    # Every completed step is scanned, and the FIRST one that reported a gate is
    # kept: later steps (closing the stream, for one) carry no ``pending`` and
    # would overwrite it with an empty list, which is exactly the false
    # negative this had.
    pending: list[dict[str, Any]] = []
    history: list[Any] = []
    for path in sorted(events_dir.glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if event.get("eventType") != "step_completed":
            continue
        outcome = _decode_payload((event.get("eventData") or {}).get("result"))
        if not isinstance(outcome, dict):
            continue
        calls = outcome.get("pending")
        if isinstance(calls, list) and calls:
            pending = [c for c in calls if isinstance(c, dict)]
            # The pass's own history rides with the gate: the resumed run
            # continues this turn, so it must carry what the first pass saw.
            history = outcome.get("history")
            history = history if isinstance(history, list) else []
            break
    if not pending:
        return None

    run_record = _run_record(run_id)
    started = _decode_payload((run_record or {}).get("input"))
    # The stored input is the workflow's own keyword arguments, as a mapping —
    # the runtime encodes them by name, not by position.
    if isinstance(started, list) and started and isinstance(started[0], dict):
        started = started[0]
    if not isinstance(started, dict):
        return None
    return {"pending": pending, "history": history, **started}


def _run_record(run_id: str) -> dict[str, Any] | None:
    """One run's stored record, read straight from its own file."""
    from berg_agents.workflow.registry import _workflow_data_dir

    path = _workflow_data_dir() / Path("runs") / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def register_workflow_routes(router: APIRouter, *, port: int) -> None:
    """Mount the queue intake and the consumer on berg's router.

    :param router: Router to attach endpoints to.
    :param port: The port berg serves on, so the runtime's queue client can be
        pointed back at berg's own intake. Threaded from ``--port`` because
        berg's port is a launch argument rather than a setting.
    """
    # Set before the consumer is built: the SDK constructs its queue client
    # lazily, and the first thing to ask for it is what happens here.
    point_queue_at_berg(port)
    consumer = build_consumer()
    # Held where the dispatcher can reach it without importing routes.
    from berg_agents.workflow import registry

    # Held where berg's own dispatcher reaches it, so the routes module
    # never imports itself to find the consumer.
    registry._CONSUMER = consumer  # ruff: ignore[private-member-access]

    @router.post(broker.QUEUE_API_PATH + "/{topic}")
    async def queue_receive(topic: str, request: Request) -> JSONResponse:
        """Record a send from the workflow runtime's queue client.

        :param topic: Queue topic, from the path.
        :param request: The send request; its body is the envelope.
        :return: The recorded message id, or null for a duplicate.
        """
        message_id = broker.enqueue(
            topic,
            await request.body(),
            idempotency_key=request.headers.get("Vqs-Idempotency-Key"),
        )
        return JSONResponse({"messageId": message_id})

    @router.post("/api/workflow/consume")
    async def workflow_consume(request: Request) -> JSONResponse:
        """The SDK's consumer, on berg's own route.

        The runtime's client reaches this only through berg's queue, but
        mounting it also makes the consumer callable directly, which is what
        the health check and any external push need.

        :param request: A delivery in the consumer's expected shape.
        :return: Whatever the SDK's consumer returns.
        """
        delivery = _Delivery(
            str(request.url), dict(request.headers), await request.body()
        )
        return JSONResponse(_as_json(await consumer(delivery)))

    @router.post("/api/workflow/turn")
    async def workflow_turn(request: Request) -> JSONResponse:
        """Start a durable turn in berg's own server, through berg's queue.

        This is step 2 of phase 1b: berg starting its own runs rather than an
        external queue client. The run goes onto berg's broker exactly as an
        SDK client's send would, so the durable properties already proven
        (resumption after a crash, a gated write, a mid-run steer) hold for
        runs berg starts itself.

        :param request: JSON body with ``prompt`` and optional ``token``.
        :return: The run id, for reading its stream and outcome back.
        """
        body = await request.json()
        from berg_agents.workflow.turn import turn
        from vercel import workflow

        token = str(body.get("token") or "").strip() or None
        run = await workflow.start(
            turn,
            token=token or _new_token(),
            prompt=str(body.get("prompt", "")),
        )
        return JSONResponse({"run_id": run.run_id})

    @router.post("/api/workflow/chat")
    async def workflow_chat(request: Request) -> JSONResponse:
        """Start a durable chat turn on berg's real chat agent.

        ``/api/chat/stream`` keeps its current host; this is the second,
        temporary one (``chat_turn._TEMPORARY_HOST``), and it exists so the
        durable host can be verified against the real agent and the real wire
        before anything moves.

        ``gate: true`` selects the gated host, where a write waits for the user
        rather than executing — the host this port exists for. The flag exists
        so the plain turn can still be reproduced, and it goes away when LiveRun
        retires and only one host is left.

        :param request: JSON body with ``prompt``, optional ``token``, the
            selections the chat path resolves, and optional ``gate``.
        :return: The run id and the token its approval route is keyed on.
        """
        from berg_agents.ui.route_handlers.chat import _resolve_active_agent
        from berg_agents.workflow.registry import point_queue_at_berg
        from vercel import workflow

        body = await request.json()
        # ONE host. The plain ``chat_turn`` this used to select could not park a
        # gated tool: without ``DeferredToolRequests`` in its output types a
        # gated call — ``delegate_task`` included — dies instead of asking, which
        # is how this was found. The gated host parks correctly and a turn with
        # no gated call is identical under it, so there is no second path.
        from berg_agents.workflow.gated_turn import gated_turn as turn_workflow

        sessions = request.app.state.sessions
        model_id = (
            request.query_params.get("model") or sessions.active_model or ""
        )
        # The session's own root dir, exactly as the chat path reads it.
        root_dir = str(sessions._harness_root_dir())
        # An explicit ``agent`` names the specialist this run is for; without
        # one the session's active agent is used, exactly as the chat path does.
        # A specialist run is otherwise identical — same host, same wire, same
        # record — which is what makes "a specialist is a run" literal.
        requested_agent = str(body.get("agent") or "").strip()
        if requested_agent:
            active_agent = requested_agent
            try:
                active_agent_description = (
                    request.app.state.harness
                    .get_agent(requested_agent)
                    .get_info()
                    .get("description")
                )
            except KeyError:
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"Unknown agent {requested_agent!r}"},
                )
        else:
            active_agent, active_agent_description = _resolve_active_agent(
                request.app.state.harness, sessions
            )
        token = str(body.get("token") or "").strip() or _new_token()
        point_queue_at_berg(port)
        run = await workflow.start(
            turn_workflow,
            token=token,
            prompt=str(body.get("prompt", "")),
            model_id=model_id,
            root_dir=root_dir,
            active_agent=active_agent,
            active_agent_description=active_agent_description,
        )
        return JSONResponse({"run_id": run.run_id, "token": token})

    @router.get("/api/workflow/chat/{run_id}/stream")
    async def workflow_chat_stream(run_id: str) -> Any:
        """Serve a durable turn's frames in the SSE protocol the UI renders.

        Same frames berg's own encoder produced, read from the durable stream —
        so a reader that joins late, or a server that restarted mid-turn, gets
        exactly the bytes the turn emitted rather than a rebuilt approximation.

        :param run_id: The turn's run id.
        :return: A streaming SSE response of ``data: {...}`` frames.
        """
        from berg_agents.workflow.registry import Frame
        from fastapi.responses import StreamingResponse

        async def _frames() -> Any:
            from vercel import workflow

            run = workflow.Run(run_id)
            async for frame in run.readable(type=Frame):
                yield frame.data
            # The protocol closes a turn with a finish frame; the turn's own
            # encoder already emitted it, so the reader only needs to stop.
            yield "data: [DONE]\n\n"

        return StreamingResponse(_frames(), media_type="text/event-stream")

    @router.post("/api/workflow/chat/{run_id}/approval")
    async def workflow_chat_approval(
        run_id: str, request: Request
    ) -> JSONResponse:
        """Answer a gated write by re-driving the run that parked on it.

        The shape is the SDK's, not mine: a deferred write means the run ENDED,
        and the decision arrives as a new run carrying history plus the answers
        (``_adapter.py:314``). On the durable host that is *better* than a hook —
        each pass is a durable run, so the decision survives because the run
        record does, and there is no process-local future to lose.

        This route answers by key: the run id, which is durable, not the token
        (the reservoir is the run id, and it is what the start route returned).

        :param run_id: The run that parked on the gate, as the start route
            returned it.
        :param request: JSON body with ``decision`` ("approved" | "rejected").
        :return: The new run's id, or 409 when that run has nothing pending.
        """
        body = await request.json()
        decision = str(body.get("decision", "rejected"))
        reason = body.get("reason")
        # An orchestrator may submit the new instruction with the decision, so it
        # does not have to write the steer store and race the turn's own read.
        steer = str(body.get("steer") or "").strip() or None

        parked = _parked_pass(run_id)
        if parked is None:
            # Nothing parked means the decision is spent: the run finished, was
            # answered already, or was stopped underneath the card. Say so
            # rather than reporting a success that changes nothing.
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "That run has no write waiting for a decision"
                },
            )
        resumed = await _resume_parked(
            run_id,
            parked,
            approved=decision == "approved",
            reason=reason,
            steer=steer,
        )
        return JSONResponse({
            "run_id": resumed,
            "decision": decision,
            "token": parked.get("token", ""),
            "agent_name": parked.get("active_agent") or ""})

    @router.post("/api/workflow/chat/{run_id}/steer")
    async def workflow_chat_steer(
        run_id: str, request: Request
    ) -> JSONResponse:
        """Send a message into a durable turn — slice c.

        A steer is stored against the run id, not held in a process, because
        ``AgentRun.enqueue`` only exists while a run is live and cannot outlive
        it. The store is what makes the text survive until the run next reads it:
        a parked run picks it up when it is resumed, and a live one picks it up
        on its next pass. Either way the text becomes a user turn in the run's
        history, which is the SDK's own rule for content arriving at a
        deferred-tool pause.

        :param run_id: The run the text is addressed to.
        :param request: JSON body with ``text``.
        :return: Confirmation, and whether anything will read it.
        """
        from berg_agents.workflow.steering import append_steer

        body = await request.json()
        text = str(body.get("text") or "")
        if not text.strip():
            return JSONResponse(
                status_code=400, content={"detail": "text is required"}
            )
        # Filed under the TURN's token, not the run id: a resumed turn is a new
        # run, so a steer keyed on the run id would be stranded the moment the
        # user's next decision starts the resumed pass. The token is what
        # identifies the conversation the user is speaking to.
        turn = _turn_token(run_id)
        append_steer(turn or run_id, text)
        return JSONResponse({"run_id": run_id, "queued": True})

    register_specialist_routes(router)

    @router.get("/api/workflow/pending")
    async def workflow_pending() -> JSONResponse:
        """Everything still in berg's queue, for diagnostics."""
        return JSONResponse({"pending": broker.pending()})


def register_specialist_routes(router: APIRouter) -> None:
    """Mount the routes an orchestrator uses to drive a specialist run.

    Separated from ``register_workflow_routes`` for the same reason the
    delegation routes are separated in ``chat.py``: these act on a *specialist*
    rather than on the queue, and keeping them together is what keeps the main
    registration under the complexity ceiling.

    :param router: Router to attach endpoints to.
    """

    @router.get("/api/workflow/chat/{run_id}/state")
    async def workflow_chat_state(run_id: str) -> JSONResponse:
        """What a specialist run is doing, in the terms a caller acts on.

        Exposed over HTTP because an orchestrator may not be this process: the
        same three answers the Python helpers give — ``waiting`` / ``working`` /
        ``pending`` / ``done`` — are what a caller needs before it decides
        whether to answer a gate, terminate, or read a report.

        :param run_id: The specialist's run id.
        :return: Its state, status and pending calls.
        """
        from berg_agents.workflow.specialists import specialist_state_async

        return JSONResponse(await specialist_state_async(run_id))

    @router.get("/api/workflow/chat/{run_id}/report")
    async def workflow_chat_report(run_id: str) -> JSONResponse:
        """What a specialist said and did, from its durable record.

        ``said`` and ``did`` rather than the raw pass record: a caller asks what
        the specialist told it and what it touched. The raw record rides under
        ``record`` for anything that needs it.

        :param run_id: The specialist's run id.
        :return: Its state, what it said, what it did, and the frame count.
        """
        from berg_agents.workflow.specialists import specialist_report_async

        report = await specialist_report_async(run_id)
        return JSONResponse(report)

    @router.post("/api/workflow/chat/{run_id}/stop")
    async def workflow_chat_stop(run_id: str, request: Request) -> JSONResponse:
        """Stop a specialist, by whichever mechanism its state needs.

        Two states, two mechanisms: a ``waiting`` run is withdrawn by denying its
        gate (its pass has already ended, so there is nothing to terminate), and
        a ``working`` run is stopped with ``Run.terminate``.

        :param run_id: The specialist's run id.
        :param request: Optional JSON body with ``reason``.
        :return: How it was stopped, and from which state.
        """
        from berg_agents.workflow.specialists import stop_specialist_async

        try:
            body = await request.json()
        except Exception:  # ruff: ignore[blind-except] - an empty body is allowed
            body = {}
        reason = str((body or {}).get("reason") or "stopped by the user")
        return JSONResponse(await stop_specialist_async(run_id, reason=reason))


def _as_json(result: Any) -> Any:
    """The consumer's response, as JSON-serialisable content."""
    body = getattr(result, "body", None)
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(bytes(body).decode())
        except (ValueError, TypeError):
            return {"ok": True}
    return {"ok": True}
