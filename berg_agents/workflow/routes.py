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
    from berg_agents.workflow.registry import wf

    # The only place these primitives exist, and not a published surface. The
    # coupling is recorded in decisions/decisions-log.md so a version bump is
    # re-checked rather than discovered in production.
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
        gated = bool(body.get("gate", False))
        if gated:
            from berg_agents.workflow.gated_turn import (
                gated_turn as turn_workflow,
            )
        else:
            from berg_agents.workflow.chat_turn import (
                chat_turn as turn_workflow,
            )

        sessions = request.app.state.sessions
        model_id = (
            request.query_params.get("model") or sessions.active_model or ""
        )
        # The session's own root dir, exactly as the chat path reads it.
        root_dir = str(sessions._harness_root_dir())
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
        from berg_agents.workflow.chat_turn import Frame
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

    @router.post("/api/workflow/chat/{token}/approval")
    async def workflow_chat_approval(token: str, request: Request) -> JSONResponse:
        """Answer a gated write on the durable host — slice b.

        The waiting half is a hook in the turn's workflow body, so the decision
        reaches it wherever the process is. This is the durable host's
        counterpart to ``POST /api/chat/delegation-approval``, and it is a
        separate route for the same structural reason that one is: the turn is
        still LIVE while the user decides.

        :param token: The turn's token, as the start route returned it.
        :param request: JSON body with ``decision`` ("approved" | "rejected").
        :return: The resumed run, or 409 when nothing is waiting on that token.
        """
        from berg_agents.workflow.gated_turn import WriteGate

        body = await request.json()
        decision = str(body.get("decision", "rejected"))
        try:
            hook = await WriteGate(
                decision=decision, reason=body.get("reason")
            ).resume(f"{token}-write")
        except Exception as exc:  # ruff: ignore[blind-except] - a spent decision must be a 409
            if "HookNotFound" in type(exc).__name__:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "No durable turn is waiting on that token"},
                )
            raise
        return JSONResponse({"resumed_run": hook.run_id, "decision": decision})

    @router.get("/api/workflow/pending")
    async def workflow_pending() -> JSONResponse:
        """Everything still in berg's queue, for diagnostics."""
        return JSONResponse({"pending": broker.pending()})


def _as_json(result: Any) -> Any:
    """The consumer's response, as JSON-serialisable content."""
    body = getattr(result, "body", None)
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(bytes(body).decode())
        except (ValueError, TypeError):
            return {"ok": True}
    return {"ok": True}
