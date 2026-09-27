"""Guardrails factory: build InputGuardrail / ToolGuardrail from hitl_rules."""

from __future__ import annotations

from typing import Any


class OutputGuardrail:
    """Audit/notify after capability invocation (notify_after rules)."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """Initialize with optional HITL rules dict."""
        self.notify_after = (rules or {}).get("notify_after", [])

    def should_notify(self, capability_id: str) -> bool:
        """Return True if capability_id is in notify_after list."""
        return capability_id in self.notify_after


class InputGuardrail:
    """Gate input params before capability invocation."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """Initialize with optional HITL rules dict."""
        self.rules = rules or {}

    def check(self, params: dict[str, Any]) -> tuple[bool, str | None]:
        """Check params against ask_before/human_leads gates."""
        rules = self.rules or {}
        ask_before = rules.get("ask_before", [])
        human_leads = rules.get("human_leads", [])
        gated = ask_before + human_leads
        # Gate if any param key matches a gated capability/tool
        for k in params:
            for gate in gated:
                if gate in str(k) or gate in str(params.get(k, "")):
                    return False, f"HITL gate: {gate} requires approval"
        # Minimal high-risk input block
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("/danger"):
                return False, f"high-risk input blocked: {k}"
        return True, None


class ToolGuardrail:
    """Gate tool invocation based on capability risk class."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """Initialize with optional HITL rules dict."""
        self.rules = rules or {}

    def allow(self, capability_id: str, risk_class: str) -> bool:
        """Allow invocation unless gated or high-risk without approval."""
        rules = self.rules or {}
        ask_before = rules.get("ask_before", [])
        human_leads = rules.get("human_leads", [])
        gated = ask_before + human_leads
        for gate in gated:
            if gate in capability_id:
                # HITL gate: deny unless explicitly approved
                return False
        return not (
            risk_class == "high" and rules.get("require_approval", True)
        )


def guardrails_from_hitl(
    hitl_rules: dict[str, Any] | None,
) -> tuple[InputGuardrail, ToolGuardrail, OutputGuardrail]:
    """Build guardrail trio from HITL rules config."""
    rules = hitl_rules or {}
    # auto_execute -> allow (no gate); ask_before/human_leads -> Input + Tool gate
    input_guard = InputGuardrail(rules)
    tool_guard = ToolGuardrail(rules)
    output_guard = OutputGuardrail(rules)
    return input_guard, tool_guard, output_guard
