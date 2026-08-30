"""Append-only, hash-chained audit log for capability invocations.

Receipts form a tamper-evident chain: each receipt's ``receipt_hash`` is
computed over the previous receipt's hash plus the current invocation
details, so altering any entry breaks every subsequent hash in the chain.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

class Receipt(BaseModel):
    """Immutable record of a single capability invocation.

    Attributes:
        request_id: Unique identifier of the invocation request.
        capability_id: Stable identifier of the invoked capability.
        status: Outcome of the invocation (e.g. "ok" | "error").
        timestamp: UTC ISO-8601 timestamp of when the receipt was created.
        prev_hash: Hash of the previous receipt in the chain (tamper link).
        receipt_hash: Hash of this receipt's own contents.
    """

    request_id: str
    capability_id: str
    status: str
    timestamp: str
    prev_hash: str
    receipt_hash: str


def _hash(*parts: str) -> str:
    """Return the SHA-256 hex digest of the pipe-joined parts.

    :param parts: Strings to hash together.
    :return: The hex digest of the concatenated parts.
    """
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only, hash-chained audit log of capability invocations.

    Receipts can only be added via :meth:`record`; they are never mutated or
    removed. Each new receipt links to the previous one through ``prev_hash``,
    providing tamper evidence for the full chain.

    Args:
        path: Optional file to persist each receipt as a JSON line.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the audit log.

        :param path: Optional file to persist each receipt as a JSON line.
        :return: None
        """
        self._path = Path(path) if path else None
        self._last_hash = "GENESIS"
        self._receipts: list[Receipt] = []

    def record(
        self, request_id: str, capability_id: str, status: str
    ) -> Receipt:
        """Append a receipt for a capability invocation.

        :param request_id: Unique identifier of the invocation request.
        :param capability_id: Stable identifier of the invoked capability.
        :param status: Outcome of the invocation (e.g. "ok" | "error").

        :return: The created receipt, chained to the previous one.
        """
        timestamp = datetime.now(UTC).isoformat()
        receipt_hash = _hash(
            self._last_hash, request_id, capability_id, status, timestamp
        )
        receipt = Receipt(
            request_id=request_id,
            capability_id=capability_id,
            status=status,
            timestamp=timestamp,
            prev_hash=self._last_hash,
            receipt_hash=receipt_hash,
        )
        self._last_hash = receipt_hash
        self._receipts.append(receipt)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(receipt.model_dump()) + "\n")
        return receipt

    def read_chain(self) -> list[Receipt]:
        """Return the full receipt chain in append order.

        :return: A copy of the receipts recorded so far; the internal log is never exposed for mutation.
        """
        return list(self._receipts)

    @property
    def last_hash(self) -> str:
        """Access the hash of the most recently recorded receipt.

        :return: The hash of the most recently recorded receipt.
        """
        return self._last_hash
