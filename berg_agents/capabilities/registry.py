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
from .base import Capability, CapabilityBase
from .envelope import InvocationRequest, InvocationResponse

from pydantic import BaseModel, ValidationError


class ToolCatalog:
    """Single source for tool routing — replaces duplicate hardlists in agents/implementation."""

    EXECUTION_KEYWORDS: tuple[str, ...] = (
        "write",
        "edit",
        "create",
        "modify",
        "delete",
        "run",
        "execute",
        "implement",
        "fix",
    )

    TOOL_REQUIREMENTS: dict[str, list[str]] = {
        "edit_file": ["read_file", "edit_file"],
        "new_file": ["new_file"],
        "read_file": ["read_file"],
        "delete_file": ["delete_file"],
        "generate_test": ["read_file", "new_file"],
        "format_code": ["read_file", "edit_file"],
        "execute_command": ["execute_command"],
    }

    @classmethod
    def tools_for(cls, task_type: str, description: str = "") -> list[str]:
        if task_type in cls.TOOL_REQUIREMENTS:
            return list(cls.TOOL_REQUIREMENTS[task_type])
        lowered = description.lower()
        if any(kw in lowered for kw in cls.EXECUTION_KEYWORDS):
            return ["read_file", "write_file", "edit_file"]
        return ["general"]


class _HarnessCapabilityWrapper:
    """Thin adapter that wraps a raw harness instance for dispatch."""

    def __init__(self, harness_instance: Any, spec: Any) -> None:
        self._instance = harness_instance
        self._spec = spec
        spec_id = getattr(spec, "id", None) or getattr(spec, "name", None)
        spec_intent = getattr(spec, "intent", None) or getattr(
            spec, "description", None
        )
        # Instance-level attributes matching the Capability protocol.
        self.id: str = str(spec_id) if spec_id else "harness-wrapper"
        self.intent: str = (
            str(spec_intent) if spec_intent else "Wrapped harness capability"
        )
        self.input_model: type[BaseModel] = BaseModel
        self.output_model: type[BaseModel] = BaseModel
        self.risk_class: str = "low"

    def invoke(self, params: BaseModel) -> BaseModel:
        result = self._instance
        if callable(getattr(self._instance, "apply", None)):
            result = self._instance.apply(params)
        elif callable(getattr(self._instance, "run", None)):
            result = self._instance.run(params)
        if isinstance(result, BaseModel):
            return result
        return BaseModel.model_validate({"value": result})


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

    def register(self, capability: Any) -> None:  # type: ignore[arg-type]
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

        if capability.risk_class == "high":
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

    def to_harness(self, spec: Any) -> Any:  # type: ignore[return-value]
        """Bridge a harness capability spec into a registered capability.

        Delegates to :func:`spec_loader.harness_capability_from_spec` so
        harness-level specs resolve to concrete instances. When the result
        is already a :class:`CapabilityBase` it is registered directly;
        otherwise a thin wrapper is built so the harness instance can be
        dispatched through this registry.

        :param spec: A harness capability spec (e.g. ``CapabilitySpec``).
        :return: A :class:`CapabilityBase` instance ready for ``register``.
        """
        from .spec_loader import harness_capability_from_spec

        instance = harness_capability_from_spec(spec)
        if instance is None:
            raise ValueError(f"harness spec could not be resolved: {spec}")
        if isinstance(instance, CapabilityBase):
            self.register(instance)
            return instance
        # Wrap a raw harness instance so it satisfies CapabilityBase.
        wrapper = _HarnessCapabilityWrapper(instance, spec)
        self.register(wrapper)
        return wrapper

    @staticmethod
    def receipt_to_dict(receipt: Receipt) -> dict[str, Any]:
        """Normalize a :class:`Receipt` to a JSON-serializable dict.

        :param receipt: The audit receipt to map.
        :return: A plain dict representation of the receipt.
        """
        return receipt.model_dump(mode="json")

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
