"""A durable queue berg owns, so workflow work survives the server dying.

Why this exists
---------------
``vercel-workflow`` runs entirely locally, and it proved out against berg in a
probe: a turn on berg's real agent and local model, steered mid-run, paused at a
gated write, resumed by the user's decision, and readable after a restart. One
thing it could not do. Its embedded queue is an in-process object — its own
module says "for in-process Queue API development" — so the moment the process
that owns it dies, nothing dispatches steps against that data dir again. A run
kept its record and stopped, forever. The standalone devserver speaks the same
protocol over HTTP but keeps messages in memory, so it fails the same way one
level down.

This module is the missing piece: a broker that speaks the SDK's queue wire
(so the SDK's own consumer can be mounted unchanged) and stores its messages in
the SQLite berg already owns (so they outlive any process). Phase 1b is additive
— nothing in the chat path changes — and the exit is to delete this module and
its one route together.

The wire, read from the installed SDK rather than assumed
---------------------------------------------------------
Send side (``vercel.queue`` client): ``POST {base}/api/v3/topic/{topic}`` with
``Authorization: Bearer <token>``, ``Vqs-Client-Ts``, and optional
``Vqs-Idempotency-Key`` / ``Vqs-Retention-Seconds`` / ``Vqs-Delay-Seconds``.

Consumer side (``vercel.workflow`` handler the SDK hands back): headers
``x-vqs-queue-name``, ``x-vqs-message-id``, ``x-vqs-message-attempt``, and a body
of ``{"payload": …, "queueName": …, "deploymentId": …}`` — the same envelope the
SDK's own local world builds when it enqueues. The consumer is a plain function
of that request, so this broker is coupled to a beta SDK's internals and has to
be re-checked whenever the SDK's version moves.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import uuid

from berg_agents.config.paths import resolve_config_dir

#: File the broker keeps queue messages in. Distinct from berg's other stores
#: (``sessions.db``, ``runs.db``, ``router_stats.db``) on purpose: a table name
#: shared with any of them is a collision waiting to happen.
QUEUE_DB_NAME = "workflow-queue.db"

#: The path the SDK's queue client posts to.
QUEUE_API_PATH = "/api/v3/topic"

#: Lease, in seconds, before an unfinished delivery is offered again.
#: A worker that dies mid-step leaves its message "in flight"; this is what
#: makes the recovery sweep re-deliver it, and it is the whole reason this
#: module exists.
DELIVERY_LEASE_SECONDS = 30


def _queue_database() -> Path:
    """The broker's database path, under berg's own config dir."""
    return resolve_config_dir(None) / QUEUE_DB_NAME


@contextmanager
def _connection() -> Generator[sqlite3.Connection, None, None]:
    """Open the broker's database, creating its schema on first use.

    Berg's own convention (``ui/session_store.py``): WAL, an explicit schema,
    commit on the way out, close in ``finally``. Kept identical so there is one
    way to open a database in this codebase.
    """
    database = _queue_database()
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS queue_messages ("
            "message_id TEXT PRIMARY KEY, "
            "topic TEXT NOT NULL, "
            "payload BLOB NOT NULL, "
            "state TEXT NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "lease_until TEXT, "
            "idempotency_key TEXT, "
            "created_at TEXT NOT NULL)"
        )
        # A retry of the same idempotency key must not double-dispatch: the
        # SDK sets the header when a step re-sends.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS queue_messages_idem "
            "ON queue_messages (idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    """UTC timestamp as the SDK's own world writes it."""
    return datetime.now(UTC).isoformat()


def enqueue(
    topic: str, payload: bytes, *, idempotency_key: str | None = None
) -> str | None:
    """Record a message for delivery.

    :param topic: Queue topic (the SDK's physical topic).
    :param payload: Transport-serialised payload, exactly as sent.
    :param idempotency_key: SDK-supplied key; a repeat insert is ignored.
    :return: The new message id, or ``None`` when it was a duplicate.
    """
    message_id = f"msg_{uuid.uuid4().hex[:22]}"
    try:
        with _connection() as conn:
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO queue_messages "
                "(message_id, topic, payload, state, attempts, created_at, "
                "idempotency_key) VALUES (?, ?, ?, 'ready', 0, ?, ?)",
                (message_id, topic, payload, _now(), idempotency_key),
            )
            # OR IGNORE means the idempotency index refused it and nothing was
            # written; returning that id would point at nothing, so the caller
            # learns it was a duplicate instead.
            return message_id if conn.total_changes > before else None
    except Exception as exc:  # a broker that cannot persist must not be silent
        print(f"[workflow-queue] enqueue failed for {topic}: {exc}")
        return None


def claim_ready(limit: int = 8) -> list[dict]:
    """Messages due for delivery, marked in flight and leased.

    Ready messages, plus any whose lease expired — which is how a step whose
    worker died gets its second attempt.

    :param limit: Maximum messages to claim in one pass.
    :return: The claimed messages as plain dicts.
    """
    try:
        with _connection() as conn:
            due = _now()
            rows = conn.execute(
                "SELECT message_id, topic, payload, attempts FROM queue_messages "
                "WHERE state='ready' OR (state='inflight' AND lease_until<=?) "
                "ORDER BY created_at LIMIT ?",
                (due, limit),
            ).fetchall()
            for message_id, _topic, _payload, attempts in rows:
                conn.execute(
                    "UPDATE queue_messages SET state='inflight', attempts=?, "
                    "lease_until=? WHERE message_id=?",
                    (attempts + 1, _lease_until(), message_id),
                )
            return [
                {
                    "message_id": str(message_id),
                    "topic": str(topic),
                    "payload": payload,
                    "attempts": int(attempts) + 1}
                for message_id, topic, payload, attempts in rows
            ]
    except Exception as exc:
        print(f"[workflow-queue] claim failed: {exc}")
        return []


def _lease_until() -> str:
    """When the current lease expires, as an ISO timestamp."""
    from datetime import timedelta

    return (
        datetime.now(UTC) + timedelta(seconds=DELIVERY_LEASE_SECONDS)
    ).isoformat()


def settle(message_id: str, *, done: bool) -> None:
    """Record a delivery's outcome.

    ``done`` removes the message; anything else releases it to be retried, which
    is what a failed step or a worker that died produces.

    :param message_id: The delivered message.
    :param done: Whether the consumer handled it.
    """
    try:
        with _connection() as conn:
            if done:
                conn.execute(
                    "DELETE FROM queue_messages WHERE message_id=?",
                    (message_id,),
                )
            else:
                conn.execute(
                    "UPDATE queue_messages SET state='ready', lease_until=NULL "
                    "WHERE message_id=?",
                    (message_id,),
                )
    except Exception as exc:
        print(f"[workflow-queue] settle failed for {message_id}: {exc}")


def pending() -> list[dict]:
    """Everything still in the queue, for diagnostics."""
    try:
        with _connection() as conn:
            rows = conn.execute(
                "SELECT message_id, topic, state, attempts FROM queue_messages "
                "ORDER BY created_at"
            ).fetchall()
            return [
                {
                    "message_id": str(message_id),
                    "topic": str(topic),
                    "state": str(state),
                    "attempts": int(attempts)}
                for message_id, topic, state, attempts in rows
            ]
    except Exception as exc:
        print(f"[workflow-queue] pending failed: {exc}")
        return []


def envelope_for(message: dict) -> dict:
    """The consumer-side body the SDK's handler reads.

    Its own local world builds exactly ``{"payload", "queueName",
    "deploymentId"}``, so this reproduces that envelope rather than inventing a
    shape and hoping the handler accepts it.
    """
    payload = message["payload"]
    if isinstance(payload, bytes):
        payload = _decode_payload(payload)
    return {
        "payload": payload,
        "queueName": message["topic"],
        "deploymentId": os.getenv("VERCEL_DEPLOYMENT_ID", "<local>")}


def _decode_payload(payload: bytes) -> object:
    """Decode a stored payload as JSON, or pass it through."""
    try:
        return json.loads(payload)
    except (ValueError, TypeError):
        return payload.decode("utf-8", errors="replace")
