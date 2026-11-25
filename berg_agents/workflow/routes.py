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


async def _answer_parked(
    run_id: str, body: dict[str, Any]
) -> dict[str, Any] | None:
    """Deliver one gate decision to the run parked on it.

    The route's whole body of work, out at module level: the parked run is
    woken through its :class:`~berg_agents.workflow.gated_turn.GateDecision`
    hook, keyed by the turn token the parked record carries, and the caller
    keeps the run id it already had.

    :param run_id: The run parked on the gate.
    :param body: The decision payload — ``decision``, optional ``reason``
        and ``steer``.
    :return: The caller's announcement (the same run id, plus the token,
        agent and model it parked with), or ``None`` when the run holds no
        pending gate.
    """
    parked = _parked_pass(run_id)
    if parked is None:
        return None

    from berg_agents.workflow.gated_turn import GateDecision, gate_token

    # resume() is a side effect that delivers a payload into a parked run;
    # from a route there is no workflow context, so it is awaited directly
    # rather than inside a step.
    decision = str(body.get("decision", "rejected"))
    await GateDecision(
        approved=decision == "approved",
        reason=body.get("reason"),
        steer=str(body.get("steer") or "").strip() or None,
    ).resume(gate_token(str(parked.get("token") or "")))
    return {
        "run_id": run_id,
        "decision": decision,
        "token": parked.get("token", ""),
        "agent_name": parked.get("active_agent") or "",
        "model": str(parked.get("model_id") or "")}


def _turn_token(run_id: str) -> str | None:
    """The turn's token for a run, from the run's own stored input.

    The token is what a steer is filed under and what the gate hook is
    keyed on — the stable name of the conversation, across replays.

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


def _specialist_sessions() -> list[dict[str, Any]]:
    """Every specialist run berg has a record of, newest first.

    A specialist is a full-scale agent with its own run, so it is a
    session that must be findable the way any launched subagent is: by
    name, by what it was asked to do, and by how it is doing — not only
    through the link in the conversation that launched it.

    The turn's own payload names the agent it runs as (``active_agent``);
    a run with none is the default chat brain, which is not a specialist.

    :return: One entry per specialist run: its id, agent, status, age,
        and the task it was given.
    """
    from berg_agents.workflow.registry import _workflow_data_dir

    runs_dir = _workflow_data_dir() / Path("runs")
    sessions: list[dict[str, Any]] = []
    for record_path in runs_dir.glob("*.json"):
        record = _run_record(record_path.stem)
        if record is None:
            continue
        started = _decode_payload(record.get("input"))
        if (
            isinstance(started, list)
            and started
            and isinstance(started[0], dict)
        ):
            started = started[0]
        if not isinstance(started, dict):
            continue
        agent = str(started.get("active_agent") or "").strip()
        if not agent:
            continue
        sessions.append({
            "runId": record_path.stem,
            "agent": agent,
            "status": str(record.get("status") or ""),
            "createdAt": record.get("createdAt"),
            "task": str(started.get("prompt") or "")[:200]})
    sessions.sort(key=lambda entry: str(entry["createdAt"] or ""), reverse=True)
    return sessions[:50]


async def _read_pass_frames(run_of_pass: str, live: bool) -> Any:
    """One pass's frames, without the tail that never ends.

    A run that ended on a gate, or was cancelled, never wrote the frame
    that closes its stream — so the SDK's ``readable`` for it tails
    forever, and replaying a turn stopped at that pass and never
    delivered the response. A pass that is not live has no more frames
    coming, so its journal is DRAINED: frames until the reader goes quiet,
    then done. A live pass is tailed, because its frames are still
    arriving and the reader wants them as they land.

    :param run_of_pass: The run whose frames are read.
    :param live: Whether the run is still working.
    :return: An async iterator of the run's SSE frame data.
    """
    import asyncio

    from berg_agents.workflow.registry import Frame
    from vercel import workflow

    run = workflow.Run(run_of_pass)
    frames = run.readable(type=Frame)
    if live:
        async for frame in frames:
            yield frame.data
        return
    iterator = aiter(frames)
    while True:
        try:
            # Two seconds of silence is the journal's end: a parked run
            # emits nothing new, ever.
            frame = await asyncio.wait_for(anext(iterator), timeout=2.0)
        except (StopAsyncIteration, TimeoutError):
            return
        yield frame.data


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

    # Every completed step is scanned, and the LATEST one that reported a pass
    # outcome decides: a turn is ONE run looping on its gate hook, so an
    # earlier pass's already-answered gate must not read as still parked —
    # the false positive that made a spent decision look pending forever.
    # (The first-gate-wins scan was written when a run held one pass; the
    # loop holds many, and only the newest says whether the run is parked.)
    latest: dict[str, Any] | None = None
    for path in sorted(events_dir.glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if event.get("eventType") != "step_completed":
            continue
        outcome = _decode_payload((event.get("eventData") or {}).get("result"))
        # Only pass outcomes carry ``pending``; steps like closing the stream
        # return None, and the steer read returns a list.
        if not isinstance(outcome, dict) or "pending" not in outcome:
            continue
        latest = outcome
    if latest is None:
        return None
    pending = [
        call for call in (latest.get("pending") or []) if isinstance(call, dict)
    ]
    # The pass's own history rides with the outcome: the next pass of the
    # loop continues this turn with what this pass saw.
    history = latest.get("history")
    history = history if isinstance(history, list) else []
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


async def _start_chat_turn(
    app: Any, body: dict[str, Any], query_model: str, port: int
) -> Any:
    """Start one durable turn for a named agent, on the ONE gated host.

    The start route's whole body of work, out at module level. An explicit
    ``agent`` names the specialist this run is for; without one the session's
    active agent is used, exactly as the chat path does. A specialist run is
    otherwise identical — same host, same wire, same record — which is what
    makes "a specialist is a run" literal.

    :param app: The FastAPI app, for the harness and the chat session.
    :param body: The request body — ``prompt``, optional ``token`` and
        ``agent``.
    :param query_model: An explicit ``model`` query parameter, when given.
    :param port: The port berg serves on, so the run's queue points home.
    :return: The FastAPI response: run id and token, or 404 for an unknown
        agent.
    """
    from berg_agents.ui.route_handlers.chat import _resolve_active_agent
    from berg_agents.workflow.gated_turn import gated_turn as turn_workflow
    from berg_agents.workflow.registry import point_queue_at_berg
    from fastapi.responses import JSONResponse
    from vercel import workflow

    sessions = app.state.sessions
    # The session's own root dir, exactly as the chat path reads it.
    root_dir = str(sessions._harness_root_dir())
    requested_agent = str(body.get("agent") or "").strip()
    if requested_agent:
        active_agent = requested_agent
        try:
            active_agent_description = (
                app.state.harness
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
            app.state.harness, sessions
        )
    # Order matters: an explicit model from the caller wins, then this
    # specialist's own choice, then the model chosen for delegated work,
    # then the chat session's model. The second rung is what lets each
    # specialist be pinned to its own brain without the orchestrator
    # knowing about the choice; the middle rung still covers the ones
    # with no choice of their own.
    model_id = (
        query_model
        or getattr(sessions, "specialist_models", {}).get(active_agent, "")
        or getattr(sessions, "delegate_model", "")
        or sessions.active_model
        or ""
    )
    token = str(body.get("token") or "").strip() or _new_token()
    point_queue_at_berg(port)
    run = await workflow.start(
        turn_workflow,
        token=token,
        prompt=str(body.get("prompt", "")),
        model_id=str(model_id),
        root_dir=root_dir,
        active_agent=active_agent,
        active_agent_description=active_agent_description,
    )
    return JSONResponse({
        "run_id": run.run_id,
        "token": token,
        # Which brain this run settled on, so the caller can say so instead
        # of leaving the choice invisible.
        "model": str(model_id)})


def _steer_turn(run_id: str, text: str) -> Any:
    """File one steer against the turn the run belongs to.

    The steer route's body, out at module level. The store is what makes the
    text survive until the run next reads it: a run parked on its gate hook
    picks the text up on the pass the decision wakes, and a live one on its
    next pass. Either way it becomes a user turn in the run's history — the
    SDK's own rule for content arriving at a deferred-tool pause.

    :param run_id: The run the text is addressed to.
    :param text: The user's instruction.
    :return: The FastAPI response: confirmation that it is queued.
    """
    from berg_agents.workflow.steering import append_steer
    from fastapi.responses import JSONResponse

    if not text.strip():
        return JSONResponse(
            status_code=400, content={"detail": "text is required"}
        )
    # Filed under the TURN's token, not the run id: the token is the stable
    # name of the conversation the user is speaking to, across every pass
    # and replay of the turn's one run.
    turn = _turn_token(run_id)
    append_steer(turn or run_id, text)
    return JSONResponse({"run_id": run_id, "queued": True})


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

        ONE host: ``gated_turn`` — the plain host this used to select could
        not park a gated tool, and a turn with no gated call is identical
        under the gated one, so there is no second path.

        :param request: JSON body with ``prompt``, optional ``token``, and
            an optional ``agent`` naming the specialist; an optional
            ``model`` query overrides the model ladder.
        :return: The run id and the token its gate hook is keyed on.
        """
        return await _start_chat_turn(
            request.app,
            await request.json(),
            request.query_params.get("model") or "",
            port,
        )

    @router.get("/api/specialists")
    async def list_specialist_sessions() -> Any:
        """The specialist sessions, newest first.

        A specialist is a run of its own: this is the index that makes
        those runs findable like any launched subagent — by agent,
        status, and the task it was given — rather than only through the
        conversation that started it.

        :return: One entry per specialist run.
        """
        return JSONResponse({"specialists": _specialist_sessions()})

    @router.get("/api/workflow/chat/{run_id}/stream")
    async def workflow_chat_stream(run_id: str, request: Request) -> Any:
        """Serve a durable turn's frames in the SSE protocol the UI renders.

        Same frames berg's own encoder produced, read from the durable stream —
        so a reader that joins late, or a server that restarted mid-turn, gets
        exactly the bytes the turn emitted rather than a rebuilt approximation.

        :param run_id: The turn's run id.
        :param request: The request, read for the resume position: the
            workflow transport tracks a chunk index and asks for the tail,
            so honouring ``startIndex`` keeps a reconnect a continuation
            rather than a second full replay folded on top of the first.
        :return: A streaming SSE response of ``data: {...}`` frames.
        """
        from fastapi.responses import StreamingResponse

        try:
            start_index = max(
                0, int(request.query_params.get("startIndex", "0"))
            )
        except ValueError:
            start_index = 0

        async def _frames() -> Any:
            # One run per turn: every pass of the loop writes the same durable
            # stream, so the addressed run's frames ARE the whole conversation
            # — there is no chain of passes to stitch, and a reader that joins
            # mid-gate sees the turn so far plus whatever the decision wakes.
            live = str(
                (_run_record(run_id) or {}).get("status") or ""
            ).lower() in {"working", "running"}
            index = 0
            async for frame_data in _read_pass_frames(run_id, live):
                if index >= start_index:
                    yield frame_data
                index += 1
            # The protocol closes a turn with a finish frame; the turn's own
            # encoder already emitted it, so the reader only needs to stop.
            yield "data: [DONE]\n\n"

        return StreamingResponse(_frames(), media_type="text/event-stream")

    @router.post("/api/workflow/chat/{run_id}/approval")
    async def workflow_chat_approval(
        run_id: str, request: Request
    ) -> JSONResponse:
        """Answer a gated write by waking the run parked on it.

        The run parks on a :class:`~berg_agents.workflow.gated_turn.GateDecision`
        hook keyed by its turn's token; this route resumes that hook and the
        SAME run continues with the decision. The run id in the answer is the
        run id in the request — a turn has one address from start to finish,
        and a caller never switches handles mid-conversation.

        :param run_id: The run parked on the gate, as the start route returned
            it.
        :param request: JSON body with ``decision`` ("approved" | "rejected"),
            optional ``reason``, and optional ``steer`` — an orchestrator may
            submit the new instruction with the decision so it does not have
            to write the steer store and race the turn's own read.
        :return: The same run id, or 409 when that run has nothing pending.
        """
        answered = await _answer_parked(run_id, await request.json())
        if answered is None:
            # Nothing parked means the decision is spent: the turn finished,
            # was answered already, or was stopped underneath the card. Say
            # so rather than reporting a success that changes nothing.
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "That run has no write waiting for a decision"
                },
            )
        return JSONResponse(answered)

    @router.post("/api/workflow/chat/{run_id}/steer")
    async def workflow_chat_steer(
        run_id: str, request: Request
    ) -> JSONResponse:
        """Send a message into a durable turn.

        :param run_id: The run the text is addressed to.
        :param request: JSON body with ``text``.
        :return: Confirmation, and whether anything will read it.
        """
        body = await request.json()
        return _steer_turn(run_id, str(body.get("text") or ""))

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
