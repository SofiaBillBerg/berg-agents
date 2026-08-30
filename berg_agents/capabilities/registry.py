"""Capability registry: registration, discovery and dispatch.

The :class:`CapabilityRegistry` is the central entry point for invoking
capabilities. It validates invocation params against each capability's
``input_model``, gates high-risk capabilities, dispatches to the capability
and records every invocation as an audit :class:`Receipt`.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from .audit import AuditLog, Receipt
from .base import Capability, RiskClass
from .envelope import InvocationRequest, InvocationResponse

from pydantic import BaseModel, ValidationError

class CapabilityRegistry:
    """Registry of capabilities with discovery and dispatch.

    Args:
        audit_log: Optional :class:`AuditLog` used to record every dispatch.
            A fresh in-memory log is created when omitted.
    """

    def __init__(self, audit_log: AuditLog | None = None) -> None:
        """Initialize the registry with an empty capability map.

        :param audit_log: Optional :class:`AuditLog` used to record every dispatch.
        :return: None
        """
        self._capabilities: dict[str, Capability] = {}
        self._audit_log = audit_log if audit_log is not None else AuditLog()

    def register(self, capability: Capability) -> None:
        """Register a capability under its ``id``.

        Registering a capability whose id is already present replaces the
        previous entry.

        :param capability: The capability instance to register.
        :return: None
        """
        self._capabilities[capability.id] = capability

    def discover(self) -> list[dict[str, Any]]:
        """Return metadata for all registered capabilities.

        :return: A list of dicts, one per capability, each containing ``id``,
            ``intent``, ``risk_class`` and the JSON schema of the
            ``input_model``.
        """
        return [
            {
                "id": capability.id,
                "intent": capability.intent,
                "risk_class": capability.risk_class,
                "input_schema": capability.input_model.model_json_schema(),
            }
            for capability in self._capabilities.values()
        ]

    def dispatch(
        self, request: InvocationRequest
    ) -> tuple[InvocationResponse, Receipt]:
        """Validate, gate and invoke a capability, recording an audit receipt.

        :param request: The invocation request to dispatch.
        :returns: A tuple of the invocation response and the audit receipt recorded
            for this dispatch.
        """
        started = time.perf_counter()
        capability = self._capabilities.get(request.capability_id)

        if capability is None:
            return self._finish(
                request,
                started,
                status="error",
                error=f"unknown capability: {request.capability_id}",
            )

        if capability.risk_class == RiskClass.HIGH:
            return self._finish(
                request,
                started,
                status="error",
                error=(
                    f"capability '{request.capability_id}' is high-risk "
                    "and requires explicit approval"
                ),
            )

        try:
            params = capability.input_model.model_validate(request.params)
        except ValidationError as exc:
            return self._finish(
                request,
                started,
                status="error",
                error=f"invalid params: {exc}",
            )

        try:
            result = capability.invoke(params)
        except Exception as exc:
            return self._finish(
                request,
                started,
                status="error",
                error=f"invocation failed: {exc}",
            )

        return self._finish(
            request, started, status="ok", result=self._to_dict(result)
        )

    def _finish(
        self,
        request: InvocationRequest,
        started: float,
        status: Literal["ok", "error"],
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> tuple[InvocationResponse, Receipt]:
        """Build the response, record the audit receipt and return both.

        :param request: The invocation request being dispatched.
        :param started: ``time.perf_counter()`` value captured at dispatch start.
        :param status: Outcome of the invocation, "ok" or "error".
        :param result: Structured result payload on success.
        :param error: Error message when status is "error".

        :return: A tuple of the invocation response and the audit receipt.
        """
        duration_ms = int((time.perf_counter() - started) * 1000)
        response = InvocationResponse(
            request_id=request.request_id,
            capability_id=request.capability_id,
            status=status,
            result=result,
            error=error,
            duration_ms=duration_ms,
        )
        receipt = self._audit_log.record(
            request_id=request.request_id,
            capability_id=request.capability_id,
            status=status,
        )
        return response, receipt

    @staticmethod
    def _to_dict(result: Any) -> dict[str, Any]:
        """Normalize an invocation result to a JSON-serializable dict.

        Uses ``mode="json"`` so that Pydantic models recursively convert
        non-JSON-safe types (e.g. ``Path``, ``datetime``, ``Enum``) into
        plain Python types before the dict is returned to the caller.

        :param result: The capability's output, typically an ``output_model``
                instance.
        :return: A JSON-serializable dict representation of the result.
        """
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if isinstance(result, dict):
            return result
        return {"value": result}
