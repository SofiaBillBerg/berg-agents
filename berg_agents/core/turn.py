# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
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

"""Session/Turn spine — one record surface for inference turns.

Phase 2 of the Session/Turn model. Centralizes the two things every
inference entry point (``execute_task``, ``chat_stream``, the generic
loop) was re-implementing on its own:

  * reading the shared context (rendered into the prompt)
  * recording the outcome once (Router Stats ) with a trace slot

The inference *mechanism* itself is unchanged — the streaming
pydantic-ai agent in ``chat_stream`` and the synchronous
``Harness._run_inference`` in ``execute_task`` keep their own shapes.
This module owns the read/record envelope around them so both paths
stop duplicating it, and carries a ``trace`` list so the rich
interaction trace (Phase 2e) has a single place to land.

Nothing here changes runtime behavior yet: ``run_turn`` is the new
surface that callers migrate onto in subsequent sub-steps. Until then,
it is available and importable, and the existing paths keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from berg_agents.core.harness._inference import _ModelUnavailableError
from berg_agents.core.interface import TaskComplexity
from berg_agents.core.shared_context import SharedContext

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """The outcome of one inference turn.

    :param answer: Displayable answer text (empty when inference did
        not run or failed).
    :param model_run: Run metadata dict (model_id, provider, usage, …).
    :param inference_attempted: Whether a model was actually invoked.
    :param shared_context: Rendered Shared Context block used for the
        turn (empty when unavailable).
    :param trace: Ordered record of what happened during the turn —
        the slot the rich interaction trace lands in.
    :param router_insight: Insight returned by the Router Stats
        (None when router_stats is disabled or recording failed).
    :param success: Whether the turn completed successfully.
    :param error: Human-readable failure reason when ``success`` is False.
    """

    answer: str = ""
    model_run: dict[str, Any] = field(default_factory=dict)
    inference_attempted: bool = False
    shared_context: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    router_insight: Any = None
    success: bool = True
    error: str | None = None


def read_shared_context(root_dir: str | None) -> str:
    """Read the effective Shared Context render for a turn.

    Project scope shadows global. Failure-isolated: a broken context
    store never breaks a turn.

    :param root_dir: Workspace root directory (None → empty).
    :return: Rendered context string, or "" when unavailable.
    """
    if not root_dir:
        return ""
    try:
        return SharedContext.resolve(root_dir).render() or ""
    except Exception as exc:  # Defensive: context must never break a turn.
        logger.warning("shared context read skipped: %s", exc)
        return ""


def record_turn_outcome(
    harness: Any,
    *,
    task_type: str,
    complexity: Any,
    description: str,
    inference_attempted: bool,
    model_used: str,
    success: bool = True,
    trace: list[dict[str, Any]] | None = None,
) -> Any:
    """Record one turn outcome via the harness Router Stats .

    Single record surface: callers should record through here instead
    of calling ``harness.router_stats.record`` directly, so the
    outcome + trace land in one place. Returns the insight (or None
    when router-stats is disabled / recording fails).

    :param trace: Optional trace list to append a record event to.
    :param harness: Harness instance exposing ``router_enabled``
        and ``router_stats``.
    :param task_type: Task type label.
    :param complexity: Routed complexity (value or enum accepted).
    :param description: Human-readable task description.
    :param inference_attempted: Whether a model was invoked.
    :param model_used: Model id that actually ran.
    :param success: Whether the turn succeeded.
    :return: Routing insight, or None.
    """
    if not getattr(harness, "router_enabled", False):
        return None
    try:
        complexity_value = getattr(complexity, "value", complexity)
        insight = harness.router_stats.record(
            {
                "task_type": task_type,
                "complexity": complexity_value,
                "description": description},
            {"success": success, "inference_attempted": inference_attempted},
            model_used=model_used,
            success=success,
        )
        return insight
    except Exception as exc:  # Defensive: recording must never break a turn.
        logger.warning("turn outcome record skipped: %s", exc)
        return None


def run_turn(
    harness: Any,
    *,
    description: str,
    task_type: str = "generic",
    complexity: TaskComplexity | None = None,
    plan: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    message_history: Any = None,
    root_dir: str | None = None,
    model: str | None = None,
    inference_attempted: bool | None = None,
    record: bool = True,
    trace: list[dict[str, Any]] | None = None,
) -> TurnResult:
    """Run one inference turn through the spine.

    Reads the Shared Context, decides whether to infer (unless the
    caller supplies ``inference_attempted``), runs the harness
    inference when applicable, records the outcome once, and returns a
    :class:`TurnResult` carrying a ``trace`` slot.

    ``_ModelUnavailableError`` is re-raised so callers keep their
    existing failure handling (e.g. building a gated/failed result).
    The outcome is recorded on success here; failure recording stays
    with the caller until the funnel sub-steps land.

    :param harness: Harness instance (owns ``_run_inference``).
    :param description: Task description for the prompt.
    :param task_type: Task type label.
    :param complexity: Routed complexity (defaults to STANDARD).
    :param plan: Planner output, if any.
    :param steps: Deterministic step templates.
    :param metadata: Task metadata (may carry ``requested_model``).
    :param message_history: Conversation to carry into inference.
    :param root_dir: Workspace root for Shared Context reading.
    :param model: Complexity-default model id label (for recording).
    :param inference_attempted: Override the inference decision.
    :param record: When True, record the outcome via the Router Stats .
    :param trace: Optional caller-owned trace list to append events to.
    :return: :class:`TurnResult`.
    :raises _ModelUnavailableError: When inference cannot run.
    """
    metadata = metadata or {}
    steps = steps or []
    if complexity is None:
        complexity = TaskComplexity.STANDARD
    if inference_attempted is None:
        try:
            inference_attempted = bool(harness._wants_inference(metadata))
        except Exception:  # Defensive.
            inference_attempted = False

    if trace is None:
        trace = []
    shared = read_shared_context(root_dir)
    trace.append({
        "event": "turn_start",
        "shared_context_present": bool(shared)})

    result = TurnResult(
        inference_attempted=inference_attempted,
        shared_context=shared,
        trace=trace,
    )

    if not inference_attempted:
        # Deterministic/no-inference path: nothing to run.
        trace.append({"event": "no_inference"})
        return result

    try:
        answer, model_run = harness._run_inference(
            description=description,
            task_type=task_type,
            complexity=complexity,
            plan=plan,
            steps=steps,
            metadata=metadata,
            message_history=message_history,
        )
    except _ModelUnavailableError:
        trace.append({"event": "inference_unavailable"})
        raise

    result.answer = answer
    result.model_run = model_run or {}
    trace.append({
        "event": "inference",
        "model": (model_run or {}).get("model_id")})

    effective_model = model or str(
        (model_run or {}).get("model_id") or "unknown"
    )
    if record:
        insight = record_turn_outcome(
            harness=harness,
            task_type=task_type,
            complexity=complexity,
            description=description,
            inference_attempted=True,
            model_used=effective_model,
            success=True,
            trace=trace,
        )
    else:
        insight = None
    result.router_insight = insight
    result.success = True
    trace.append({"event": "recorded", "insight": bool(insight)})
    return result
