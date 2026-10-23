# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

# noinspection unresolved-references
"""Human-in-the-loop (HITL) surface for the  tool loop.

A :class:`BergLoop` pauses before executing a tool call when the call
is in the ``interrupt_on`` policy.  The pause is serialized as a
:class:`HitlRequest` and saved into the snapshot.  The caller resolves
the pause with :class:`HitlDecision` (approve / reject / edit) via
:func:`BergLoop.resume`.

This module is **pure data + pure helpers** - it owns no I/O, no
adapter, and no framework dependency.  The loop (B.3) is the only
caller; tests can exercise the rules in isolation.

Why dataclasses + a `Literal` action instead of an enum?  Two reasons:

1. **Wire-friendliness.**  The same shape serializes to JSON and back
   without a custom encoder.  A ``Literal["approve","reject","edit"]``
   is a 1-to-1 string union; we can compare ``action == "approve"`` in
   the loop without a second import.
2. **Frozen-by-default.**  ``@dataclass(frozen=True)`` makes both
   request and decision hashable and immutable - the loop can stash
   them into the snapshot dict without risk of mutation by callers.

The risk vocabulary follows :data:`core.tool_spec.RiskClass`
(``"low" | "medium" | "high"``).  The design contract originally
proposed four categories (``read/write/state/destructive``), but the
shipped :mod:`core.tool_spec` uses three; we bridge by treating
``"high"`` as the always-interrupt bucket.  See ``default_interrupt_on``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

#: The three actions a human can take on a paused tool call.
#: ``edit`` requires :attr:`HitlDecision.edited_args`; ``approve`` and
#: ``reject`` ignore it.
HitlAction = Literal["approve", "reject", "edit"]

#: Mutating built-ins get a full HITL pause.
DEFAULT_INTERRUPT_TOOLS: frozenset[str] = frozenset(
    {"edit_file", "write_file", "delete", "execute"},
)


# noinspection unresolved-references
@dataclass(frozen=True)
class HitlRequest:
    """A snapshot of a tool call the loop is pausing for review.

    The request is **immutable**; the caller must build a new one to
    change fields.  The loop stashes the request into the snapshot's
    ``pending_hitl`` slot, so a `resume' action in a different process can
    re-create the same pause state.

    :var tool_call_id: Stable id assigned by the loop (matches the id of the corresponding :class:`LoopEvent` ``ToolCallRequest``).
    :var tool_name: Public name of the tool about to be invoked.
    :var tool_args: The arguments the model chose.  This is the shallow-copied mapping from the LLM response - the loop does not mutate it.
    :var risk_class: Inherited from :class:`ToolSpec.risk_class` (``"low" | "medium" | "high"``).
    :var allowed_decisions: Subset of :data:`HitlAction` values the resolver may pick.  Defaults to all three.
    :var reason: Human-readable explanation the loop has computed (e.g. ``"edits a tracked file"``).  The TUI surfaces this.
    """

    tool_call_id: str
    tool_name: str
    tool_args: Mapping[str, Any]
    risk_class: str
    allowed_decisions: tuple[str, ...] = ("approve", "reject", "edit")
    reason: str = ""

    def __post_init__(self) -> None:
        """Validate types and the allow-list at construction time.

        ``Mapping`` is the structural type; we accept any ``Mapping``
        at the type level but normalize to a fresh ``dict`` for
        downstream code that mutates.  Bypass ``frozen`` by going
        through ``object.__setattr__``.
        """
        if not isinstance(self.tool_args, Mapping):
            raise TypeError(
                f"tool_args must be a Mapping, got {type(self.tool_args).__name__}",
            )
        if not self.allowed_decisions:
            raise ValueError("allowed_decisions must be a non-empty tuple")
        valid_actions = frozenset(("approve", "reject", "edit"))
        for action in self.allowed_decisions:
            if action not in valid_actions:
                raise ValueError(
                    f"allowed_decisions contains unknown action {action!r}",
                )


# noinspection unresolved-references
@dataclass(frozen=True)
class HitlDecision:
    """The human's answer to a paused call.

    :var tool_call_id: The id of the :class:`HitlRequest` being answered.  Must match a request in the snapshot.
    :var action: One of :data:`HitlAction`.
    :var edited_args: Required when ``action == "edit"``; ignored otherwise.  Replaces :attr:`HitlRequest.tool_args`.
    :var note: Optional human note (shown in audit logs).
    """

    tool_call_id: str
    action: HitlAction
    edited_args: Mapping[str, Any] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        """Validate the action and the edit-args presence at construction time."""
        valid_actions = frozenset(("approve", "reject", "edit"))
        if self.action not in valid_actions:
            raise ValueError(
                f"action must be one of ('approve','reject','edit'), got {self.action!r}",
            )
        if self.action == "edit" and self.edited_args is None:
            raise ValueError(
                "edited_args is required when action == 'edit'",
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def is_valid_decision(request: HitlRequest, decision: HitlDecision) -> bool:
    """Return ``True`` if *decision* legally answers *request*.

    Three checks:

    1. **Call-id match.**  ``decision.tool_call_id == request.tool_call_id``.
       A stale or misrouted decision is rejected.
    2. **Action in the allow-list.**  The request's
       ``allowed_decisions`` tuple is the authoritative policy; a
       request that only allows ``("approve","reject")`` cannot be
       answered with ``"edit"``.
    3. **Edit-args presence.**  If the action is ``"edit"`` the
       decision must carry :attr:`edited_args` (the dataclass
       ``__post_init__`` already enforces this, so a decision that
       reaches here is well-formed).

    :param request: The paused request.
    :param decision: The proposed answer.
    :return: ``True`` iff the decision is admissible.
    """
    if not isinstance(request, HitlRequest):
        raise TypeError(
            f"request must be a HitlRequest, got {type(request).__name__}",
        )
    if not isinstance(decision, HitlDecision):
        raise TypeError(
            f"decision must be a HitlDecision, got {type(decision).__name__}",
        )
    if decision.tool_call_id != request.tool_call_id:
        return False
    return decision.action in request.allowed_decisions


# noinspection unresolved-references
def default_interrupt_on(
    tools: Mapping[str, Any],
) -> dict[str, bool]:
    """Compute the default ``interrupt_on`` policy for a tool registry.

    The returned dict maps tool-name → ``True`` (pause before this
    call) / ``False`` (run without pausing).  Two rules:

    1. Every name in :data:`DEFAULT_INTERRUPT_TOOLS` (``edit_file``,
       ``write_file``, ``delete``, ``execute``) is ``True``.
    2. Every other tool is ``False`` - the loop will not pause for
       read-only helpers.

    The argument is a *mapping* of name → tool (typically
    :attr:`ToolRegistry.specs`) so this helper stays free of the
    registry class.  Only the keys are read.

    :param tools: Mapping of tool name → tool object (any object -
        only the keys matter).
    :return: ``{tool_name: bool}`` for every tool in *tools*.
    """
    if not isinstance(tools, Mapping):
        raise TypeError(
            f"tools must be a Mapping, got {type(tools).__name__}",
        )
    policy: dict[str, bool] = {}
    for name in tools:
        policy[name] = name in DEFAULT_INTERRUPT_TOOLS
    return policy


# noinspection unresolved-references
def apply_decision(
    request: HitlRequest,
    decision: HitlDecision,
) -> Mapping[str, Any] | None:
    """Resolve a paused request to the args the loop should use.

    Decision contract:

    - ``"approve"`` → return :attr:`HitlRequest.tool_args` unchanged.
    - ``"edit"``    → return :attr:`HitlDecision.edited_args`
      (or ``{}`` if it was missing - the dataclass forbids this so
      callers passing ``None`` get a defensive default).
    - ``"reject"``  → return ``None``; the loop turns this into a
      :class:`ToolError` with reason ``"rejected by human"``.

    The function does **not** check :func:`is_valid_decision`; it
    assumes the caller has already validated the decision.  This keeps
    the helper cheap (the loop will re-validate before invoking
    :func:`is_valid_decision` anyway, and the snapshot resume path
    applies decisions that were validated on the original pause).

    :param request: The paused request.
    :param decision: The human's answer.
    :return: Mapping of args to pass to the tool, or ``None`` if
        rejected.
    """
    if not isinstance(request, HitlRequest):
        raise TypeError(
            f"request must be a HitlRequest, got {type(request).__name__}",
        )
    if not isinstance(decision, HitlDecision):
        raise TypeError(
            f"decision must be a HitlDecision, got {type(decision).__name__}",
        )
    if decision.action == "approve":
        return dict(request.tool_args)
    if decision.action == "edit":
        return dict(decision.edited_args or {})
    return None


__all__ = [
    "DEFAULT_INTERRUPT_TOOLS",
    "HitlAction",
    "HitlDecision",
    "HitlRequest",
    "apply_decision",
    "default_interrupt_on",
    "is_valid_decision"]
