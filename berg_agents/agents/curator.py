"""Curator agent for berg_agents.

Updates documentation, manages memory and context files,
distills learnings from completed tasks, and keeps project
knowledge fresh.

The curator step runs only when ``files_changed`` is present
in the task metadata. The harness (subtask 11) must call
:func:`should_run_curator` first and skip the curator when
the gate is closed.
"""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import logging

from typing import Any


# Module logger covering curator gate skips.
logger = logging.getLogger(__name__)

__all__ = [
    "CURATION_KEYWORDS",
    "CURATION_TASK_TYPES",
    "build_update_plan",
    "curate_task",
    "curation_confidence",
    "determine_actions",
    "should_run_curator"]

# Task types the curator handles with full confidence.
# Mirrors the curation_types set of the old Curator class.
CURATION_TASK_TYPES: frozenset[str] = frozenset({
    "context_sync",
    "curate",
    "distill",
    "document",
    "memory_update",
    "summarize",
    "update_docs"})

# Keywords matching documentation/memory work in a free-text
# description; partial (0.7) confidence, as before.
CURATION_KEYWORDS: tuple[str, ...] = (
    "context",
    "document",
    "memory",
    "update docs",
    "update readme",
)

# Complexity levels that trigger a fallback knowledge update
# when no concrete actions were derived from metadata.
COMPLEX_FALLBACK: frozenset[str] = frozenset({"complex", "critical"})

# Where distilled patterns are recorded by default.
PATTERN_TARGET = "context/examples/"

# Where architecture decisions are recorded by default.
DECISION_TARGET = "decisions/decisions-log.md"

# Fallback knowledge target for complex tasks with no metadata.
KNOWLEDGE_TARGET = "context/technical-domain.md"


def should_run_curator(
    metadata: dict[str, Any] | None,
) -> bool:
    """Gate the curator step on ``files_changed`` metadata.

    The curator runs only when the task metadata carries a
    non-empty ``files_changed`` list, per the orchestration
    behavior spec. The harness must check this first.

    Args:
        metadata: Task metadata mapping, or ``None``.

    Returns:
        True only when ``files_changed`` is present, is a
        list, and holds at least one non-blank path.
    """
    # No metadata means no evidence of file changes: skip.
    if not metadata:
        return False
    files_changed = metadata.get("files_changed")
    # A non-list value (e.g. a stray string) never opens
    # the gate; only an explicit list of paths does.
    if not isinstance(files_changed, list):
        return False
    return any(isinstance(path, str) and path.strip() for path in files_changed)


def curation_confidence(task: dict[str, Any]) -> float:
    """Score how strongly a task needs curation.

    Preserves the old can_handle semantics: full confidence
    for known curation task types, partial on keyword match,
    minimal otherwise.

    Args:
        task: Task mapping with ``task_type``/``description``.

    Returns:
        Confidence in [0.0, 1.0].
    """
    task_type = task.get("task_type", "")
    # Exact task-type match is the strongest signal.
    if task_type in CURATION_TASK_TYPES:
        return 1.0
    description = task.get("description", "").lower()
    # Keyword match on free text is a weaker signal.
    if any(key in description for key in CURATION_KEYWORDS):
        return 0.7
    return 0.1


def determine_actions(
    task: dict[str, Any],
    metadata: dict[str, Any],
    complexity: str = "standard",
) -> list[dict[str, Any]]:
    """Derive curation actions from task metadata.

    Pure function: same inputs always yield the same action
    list, with no side effects.

    Args:
        task: Task mapping (kept for signature parity).
        metadata: Task metadata with optional ``files_changed``,
            ``patterns``, and ``decisions`` entries.
        complexity: Complexity label driving the fallback.

    Returns:
        List of action descriptor mappings.
    """
    _ = task  # Reserved for future task-driven actions.
    actions: list[dict[str, Any]] = []

    # One documentation action per changed source file.
    files_changed = metadata.get("files_changed", [])
    if isinstance(files_changed, list):
        for path in files_changed:
            if isinstance(path, str) and path.strip():
                actions.append({
                    "action": "update_docs",
                    "target": path,
                    "type": "code_documentation"})

    # One record action per distilled pattern.
    patterns = metadata.get("patterns", [])
    if isinstance(patterns, list):
        for pattern in patterns:
            actions.append({
                "action": "record_pattern",
                "content": pattern,
                "target": PATTERN_TARGET,
                "type": "pattern"})

    # One append action per architecture decision.
    decisions = metadata.get("decisions", [])
    if isinstance(decisions, list):
        for decision in decisions:
            actions.append({
                "action": "record_decision",
                "content": decision,
                "target": DECISION_TARGET,
                "type": "decision"})

    # Fallback: complex tasks with no concrete metadata still
    # refresh the technical-domain knowledge file.
    if not actions and complexity in COMPLEX_FALLBACK:
        actions.append({
            "action": "update_context",
            "target": KNOWLEDGE_TARGET,
            "type": "knowledge_update"})

    return actions


def build_update_plan(
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Order curation actions into numbered update steps.

    Group order is stable: docs, then patterns, then
    decisions, then knowledge updates.

    Args:
        actions: Action descriptors from determine_actions.

    Returns:
        Ordered list of numbered update step mappings.
    """
    plan: list[dict[str, Any]] = []

    def _add_step(action: str, target: str, description: str) -> None:
        """Append one numbered step to the plan."""
        # Step numbers are 1-based and follow insertion order.
        plan.append({
            "action": action,
            "description": description,
            "step": len(plan) + 1,
            "target": target})

    # Docs first: keep generated references in sync early.
    for item in actions:
        if item.get("type") == "code_documentation":
            _add_step(
                "update",
                str(item.get("target", "")),
                f"Update documentation for {item.get('target', '')}",
            )

    # Patterns second: record reusable knowledge.
    for item in actions:
        if item.get("type") == "pattern":
            content = str(item.get("content", ""))[:50]
            _add_step(
                "append",
                str(item.get("target", "")),
                f"Record new pattern: {content}",
            )

    # Decisions third: append to the decisions log.
    for item in actions:
        if item.get("type") == "decision":
            _add_step(
                "append",
                str(item.get("target", "")),
                "Record architecture decision",
            )

    # Knowledge updates last: broadest, lowest priority.
    for item in actions:
        if item.get("type") == "knowledge_update":
            _add_step(
                "update",
                str(item.get("target", "")),
                "Update technical domain knowledge",
            )

    return plan


def curate_task(
    task: dict[str, Any],
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run the files_changed-gated curation step (harness entry).

    This is the whole curator step: gate check plus
    action/plan derivation, deterministic and LLM-free.
    The harness calls this after implementation.

    Args:
        task: Task mapping with type/description/complexity.
        metadata: Task metadata carrying ``files_changed``.

    Returns:
        ``{"status": "skipped", ...}`` when the gate is
        closed, else ``{"status": "curated", ...}`` with
        actions, update plan, and files to update.
    """
    # Gate first: no changed files means no curation work.
    if not should_run_curator(metadata):
        logger.debug("Curator skipped: no files_changed.")
        return {
            "actions": [],
            "files_to_update": [],
            "reason": "no files_changed in task metadata",
            "status": "skipped",
            "update_plan": []}

    # Gate is open; metadata is a non-empty mapping here.
    assert metadata is not None
    complexity = str(task.get("complexity", "standard"))
    actions = determine_actions(task, metadata, complexity)
    update_plan = build_update_plan(actions)
    return {
        "actions": actions,
        "files_to_update": [str(item.get("target", "")) for item in actions],
        "status": "curated",
        "task_type": task.get("task_type", "generic"),
        "update_plan": update_plan}
