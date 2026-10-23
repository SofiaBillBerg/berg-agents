# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Routing helpers for Harness - HITL gates, mutation checks, agent selection."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from berg_agents.agents.guardian import GuardianDecision
from berg_agents.capabilities.registry import ToolCatalog
from berg_agents.core.hitl import DEFAULT_INTERRUPT_TOOLS
from berg_agents.core.interface import RiskLevel, TaskComplexity
from berg_agents.core.learning_gate import LearningGate
from berg_agents.core.tool_spec import ToolSpec

logger = logging.getLogger(__name__)

#: Complexity levels ascending — the routing lever. Higher levels resolve
#: to heavier models (resolve_implementation_model maps complexity onto a
#: model tier) and, at the top, always pause for human review.
_COMPLEXITY_ORDER = (
    TaskComplexity.TRIVIAL,
    TaskComplexity.STANDARD,
    TaskComplexity.COMPLEX,
    TaskComplexity.CRITICAL,
)


def _shift_complexity(
    complexity: TaskComplexity, direction: str
) -> TaskComplexity:
    """Shift a complexity one bounded step in a learning direction.

    A sustained-failure ``"up"`` step routes harder; a high-success
    ``"down"`` step routes cheaper. Clamped to the level range so a
    sequence of adjustments can never escape the enum.

    :param complexity: Baseline complexity from ``estimate_complexity``.
    :param direction: ``"up"`` or ``"down"`` (anything else is a no-op).
    :return: The shifted complexity level.
    """
    try:
        index = _COMPLEXITY_ORDER.index(complexity)
    except ValueError:
        return complexity
    if direction == "up":
        index = min(index + 1, len(_COMPLEXITY_ORDER) - 1)
    elif direction == "down":
        index = max(index - 1, 0)
    return _COMPLEXITY_ORDER[index]


@dataclass
class _AgentCard:
    """Display/override card for non-facade agents.

    Agents without an ``AbstractAgent`` facade (guardian,
    implementation, curator, learning) still appear in the
    catalog and accept complexity overrides, so they get a card
    carrying the same fields ``AbstractAgent.get_info``
    reports. Cards are display metadata only; routing uses
    the confidence functions, not these levels.

    Attributes:
        name: Registry key and display name.
        description: One-line role description.
        preferred_complexity: Default complexity, overridable.
        capabilities: Capability labels for the catalog.
    """

    name: str
    description: str
    preferred_complexity: str = "standard"
    capabilities: list[str] = field(default_factory=list)

    def get_info(self) -> dict[str, Any]:
        """Return catalog info matching the agent contract.

        Returns:
            Mapping with name, description, complexity, and
            capabilities keys.
        """
        # Copy the list so callers cannot mutate the card.
        return {
            "name": self.name,
            "description": self.description,
            "preferred_complexity": self.preferred_complexity,
            "capabilities": list(self.capabilities)}


def _tool_is_mutating(tool_name: str) -> bool:
    """Check whether a planned tool can mutate state.

    ``"general"`` never mutates; tools whose names carry a
    read-only hint (per :class:`ToolSpec.is_read_only`)
    never mutate; anything in ``DEFAULT_INTERRUPT_TOOLS``
    or prefixed by one of its entries (``delete_file``,
    ``execute_command``) may mutate.

    :param tool_name: Planned tool name.
    :return: True when the tool may mutate state.
    """
    if tool_name == "general":
        return False
    if ToolSpec(name=tool_name, description="").is_read_only:
        return False
    lowered = tool_name.lower()
    return any(
        lowered == interrupt.lower()
        or lowered.startswith(interrupt.lower() + "_")
        for interrupt in DEFAULT_INTERRUPT_TOOLS
    )


def _task_plans_mutation(task_type: str, description: str = "") -> bool:
    """Check whether a task plans any mutating tool.

    The task type itself may name a mutating tool
    (``"execute"``, ``"delete"``, ``"write_file"`` fall
    back to a general tool plan), so it is checked
    alongside the planned tool list and description keywords.

    :param task_type: Task type used for tool planning.
    :param description: Free-text task description.
    :return: True when at least one planned tool may mutate.
    """
    if _tool_is_mutating(task_type):
        return True
    if any(
        _tool_is_mutating(name)
        for name in ToolCatalog.tools_for(task_type, description)
    ):
        return True
    if description:
        lowered = description.lower()
        if any(
            kw in lowered
            for kw in (
                "write",
                "edit",
                "create",
                "modify",
                "delete",
                "run",
                "execute",
                "implement",
            )
        ):
            return True
    return False


def _confidence_gate_bypassed(
    verdict: GuardianDecision, task_type: str, description: str = ""
) -> bool:
    """Check whether a review verdict skips the human gate.

    A verdict never gates tasks whose planned tools are all
    read-only, so conversation and lookup work proceeds
    while mutating tool calls still pause for approval.
    High/critical risk and critical complexity always gate.

    :param verdict: Guardian review verdict.
    :param task_type: Task type used for tool planning.
    :param description: Free-text task description.

    :return:        True when the gate may be bypassed.
    """
    if verdict.risk_level in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}:
        return False
    if verdict.complexity == TaskComplexity.CRITICAL.value:
        return False
    return not _task_plans_mutation(task_type, description)


def _failed_result(
    *,
    resolved_id: str,
    task_type: str,
    description: str,
    complexity: TaskComplexity,
    verdict: GuardianDecision,
    model: str,
    error: str,
    learning_gate: LearningGate | None,
) -> dict[str, Any]:
    """Build the model-unavailable failure result.

    Shared by the chat bypass and the main inference path;
    both report the same shape with ``inference_attempted=True``.

    :param resolved_id: Caller thread id.
    :param task_type: Task type label.
    :param description: Human-readable task description.
    :param complexity: Routed complexity.
    :param verdict: Guardian review verdict (risk reporting only).
    :param model: Complexity-default model id label.
    :param error: Human-readable failure reason.
    :param learning_gate: Gate recording the failure, or None to skip.

    :return:        Failure result dict.
    """
    failed: dict[str, Any] = {
        "status": "failed",
        "task_id": resolved_id,
        "task_type": task_type,
        "complexity": complexity.value,
        "risk_level": verdict.risk_level,
        "model": model,
        "error": error,
        "inference_attempted": True}
    if learning_gate is not None:
        failed["learning"] = learning_gate.record(
            {
                "task_type": task_type,
                "complexity": complexity.value,
                "description": description},
            {"success": False, "inference_attempted": True},
            model_used=model,
            success=False,
        )
    return failed


def _extract_planned_actions(raw: Any) -> list[dict[str, Any]] | None:
    """Parse the model's planned-actions JSON into action requests.

    Tolerant extraction: strips code fences, finds the first JSON
    array in the text, and normalizes each entry to
    ``{"action": <tool>, "args": {...}}``. Anything not a proper
    list of objects yields None so the caller falls back to the
    placeholder action list.

    :param raw: Raw model output (string or any object).

    :return:        Normalized action list, or None when parsing failed.
    """
    if not isinstance(raw, str):
        raw = str(raw or "")
    text = raw.strip()
    # Strip markdown code fences the model may add.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    actions: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            return None
        tool = item.get("tool") or item.get("action")
        if not isinstance(tool, str) or not tool.strip():
            return None
        # Everything except the tool/action key becomes the args;
        # an explicit "args" mapping wins when present.
        args = item.get("args")
        if not isinstance(args, dict):
            args = {
                k: v for k, v in item.items() if k not in {"tool", "action"}
            }
        actions.append({"action": tool.strip(), "args": args})
    return actions or None


def _apply_mutation_guard(
    verdict: GuardianDecision, task_type: str, description: str
) -> GuardianDecision:
    """Force the HITL gate for mutating tool plans.

    Mutating tool calls always pause for approval, even when the
    guardian auto-executes: a confident edit is still an edit.
    Non-mutating tasks (chat/general queries) bypass guardian
    human review gates entirely.

    :param verdict: Guardian review verdict to adjust.
    :param task_type: Task type used for tool planning.
    :param description: Free-text task description.

    :return:        An updated verdict copy; the input is left untouched.
    """
    if not _task_plans_mutation(task_type, description):
        return verdict.model_copy(update={"needs_human_review": False})
    if not verdict.needs_human_review:
        return verdict.model_copy(
            update={
                "needs_human_review": True,
                "reasons": [
                    f"Mutating action required: task '{description[:60]}...' (type: {task_type}) requires human approval before file/tool mutation"
                ]}
        )
    return verdict


def _review_gate_result(
    *,
    verdict: GuardianDecision,
    task_type: str,
    description: str,
    resolved_id: str,
    confidence: float,
    approved: bool,
    action_requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Apply the human-review gate.

    An approved resume skips the gate but keeps the verdict for
    risk reporting; a low-confidence-only verdict whose planned
    tools are all read-only is bypassed the same way. When the
    orchestrator pre-planned concrete mutating actions (a
    read-only planning inference), ``action_requests`` carries
    the model's real tool calls - with actual file paths - so
    the HITL card shows what will truly happen.

    :param verdict: Guardian review verdict (already mutation-guarded).
    :param task_type: Task type label.
    :param description: Human-readable task description.
    :param resolved_id: Caller thread id for log lines.
    :param confidence: Routing confidence score.
    :param approved: True when metadata records a human approval.
    :param action_requests: Pre-planned concrete mutating actions,
        if planning inference ran, else None.

    :return:        The ``needs_human_review`` result dict when the task must
        pause, else None to let execution proceed.
    """
    if not verdict.needs_human_review:
        return None
    if approved:
        logger.info(
            "Task %s approved by human; proceeding despite: %s",
            resolved_id,
            verdict.reasons,
        )
        return None
    if _confidence_gate_bypassed(verdict, task_type, description):
        logger.info(
            "Task %s low confidence only with read-only"
            " tools; proceeding without review",
            resolved_id,
        )
        return None
    logger.info(
        "Task %s gated for human review: %s",
        resolved_id,
        verdict.reasons,
    )
    # Structured actions for the HITL card: prefer the model's
    # concrete pre-planned actions (real paths), else fall back
    # to the ToolCatalog placeholder list.
    if not action_requests:
        tools = ToolCatalog.tools_for(task_type, description)
        action_requests = [
            {"action": tool, "args": {"description": description[:120]}}
            for tool in tools
        ]
    return {
        "status": "needs_human_review",
        "task_id": resolved_id,
        "task_type": task_type,
        "complexity": verdict.complexity,
        "risk_level": verdict.risk_level,
        "review_reasons": list(verdict.reasons),
        "confidence": confidence,
        "action_requests": action_requests,
        "inference_attempted": False}
