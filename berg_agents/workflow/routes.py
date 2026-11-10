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


def register_workflow_routes(router: APIRouter) -> None:
    """Mount the queue intake and the consumer on berg's router.

    :param router: Router to attach endpoints to.
    """
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
