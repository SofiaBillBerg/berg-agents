# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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
# along with this program.  If not, see <https://gnu.org/licenses/agpl.html>.

r"""Normalize and repair ``ask_user_question`` calls the local model writes.

Two failures, one root: the harness's ask_user tool ADVERTISES
``options: ["str", ...]`` in the schema the model sees, while its runtime
signature wants ``[{"label": ...}, ...]``. A local model follows the
advertised schema, writes strings, and the call-time check (which
validates against the advertised schema) passes. Then:

1. the ANSWER path re-validates against the real function signature and
   rejects the strings — ``question answer skipped for <id>: 5 validation
   errors`` — so the run cannot continue past the question; and
2. the UI's card, reading the parked call's recorded arguments, cannot
   parse options it was never promised.

This capability covers both sides of the seam:

- :meth:`AskUserRepair.wrap_tool_validate` runs on EVERY call and
  normalizes the SHAPE (an option string becomes an option object), so
  the answer path validates and the run continues;
- :meth:`AskUserRepair.on_tool_validate_error` remains the repair for the
  values themselves (an over-long header — the harness caps it at 25
  characters and a 9B model does not count — which pydantic-ai retries
  three times before killing the turn).

Both are bound to the harness's own constants, so neither can enforce a
number or a shape the harness does not; anything with no honest repair
re-raises rather than being silently invented.
"""


from __future__ import annotations

import json
import logging
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai_harness.ask_user import TOOL_NAME

# The harness's ask_user limits. Bound from its private module — the
# constants are not re-exported publicly — so this repair enforces the
# harness's own numbers rather than a copy that could drift.
from pydantic_ai_harness.ask_user._types import (  # ruff: ignore[import-private-name]
    MAX_HEADER_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_OPTIONS,
    MAX_QUESTION_LENGTH,
    MIN_OPTIONS,
)

logger = logging.getLogger(__name__)

#: The harness tool whose arguments this repairs (its public export).
ASK_USER_TOOL_NAME = TOOL_NAME

#: A clipped label keeps an ellipsis so a truncation is visible rather
#: than looking like the model's own (short) choice.
_ELLIPSIS = "…"


def _clip(text: str, limit: int) -> str:
    """Bring a string inside a length limit, visibly.

    :param text: The model's text.
    :param limit: The harness's limit for the field.
    :return: The text, clipped to the limit when longer.
    """
    if len(text) <= limit:
        return text
    # Reserve the ellipsis inside the limit, then drop any trailing
    # space the cut left behind.
    return f"{text[: max(0, limit - len(_ELLIPSIS))].rstrip()}{_ELLIPSIS}"


def _repair_option(option: Any, label_limit: int) -> dict[str, Any] | None:
    """Bring one option inside the harness's shape.

    :param option: The model's option object.
    :param label_limit: The harness's label limit.
    :return: A repaired option, or None when it has no label to keep.
    """
    if not isinstance(option, dict):
        return None
    label = option.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    repaired: dict[str, Any] = {"label": _clip(label.strip(), label_limit)}
    description = option.get("description")
    if isinstance(description, str) and description.strip():
        repaired["description"] = description.strip()
    return repaired


def _repair_options(raw_options: Any) -> list[dict[str, Any]]:
    """Bring a question's options inside the harness's shape.

    :param raw_options: The model's options.
    :param limits: The harness's ask_user module.
    :return: Repaired options, within the harness's count range.
    """
    options: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for option in raw_options or []:
        repaired = _repair_option(option, MAX_LABEL_LENGTH)
        if repaired is None or repaired["label"] in seen_labels:
            continue
        seen_labels.add(repaired["label"])
        options.append(repaired)
    # Below the minimum, a neutral choice keeps the question answerable;
    # above the maximum, the first ones are the model's own ordering, so
    # the tail is what goes.
    while len(options) < MIN_OPTIONS:
        filler = _clip(f"Other {len(options) + 1}", MAX_LABEL_LENGTH)
        if filler in seen_labels:
            break
        seen_labels.add(filler)
        options.append({"label": filler})
    return options[:MAX_OPTIONS]


def _unique_header(header: str, seen: set[str], limit: int) -> str:
    """Make a header unique within a call, inside the length limit.

    The base is clipped to leave room for the counter, so a header that
    already fills the limit still produces DIFFERENT candidates per
    attempt rather than the same clipped string forever.

    :param header: The (already clipped) header.
    :param seen: Headers already used by this call.
    :param limit: The harness's header limit.
    :return: A unique header.
    """
    if header not in seen:
        return header
    base = header
    for attempt in range(2, 100):
        tag = f" {attempt}"
        base = _clip(base, max(1, limit - len(tag)))
        candidate = f"{base}{tag}"
        if candidate not in seen:
            return candidate
    # A call with MAX_QUESTIONS (10) questions cannot reach here; the
    # numbered suffixes alone outnumber the headers that can collide.
    return _clip(f"{base} 99", limit)


def _repair_question(
    question: Any, seen_headers: set[str]
) -> dict[str, Any] | None:
    """Bring one question inside the harness's shape.

    :param question: The model's question object.
    :param seen_headers: Headers already used by this call.
    :return: A repaired question, or None when it has no question text.
    """
    if not isinstance(question, dict):
        return None
    text = question.get("question")
    # A question needs its text: without it there is nothing to ask.
    if not isinstance(text, str) or not text.strip():
        return None
    header = question.get("header")
    if not isinstance(header, str) or not header.strip():
        # The header is the answer's key; a missing one is derived from
        # the question's first words rather than dropped.
        header = " ".join(text.split()[:4])
    header = _clip(header.strip(), MAX_HEADER_LENGTH)
    header = _unique_header(header, seen_headers, MAX_HEADER_LENGTH)
    seen_headers.add(header)
    return {
        "header": header,
        "question": _clip(text.strip(), MAX_QUESTION_LENGTH),
        "options": _repair_options(question.get("options")),
        # An absent or non-boolean multi_select reads as False: the
        # harness wants a real boolean, not a truthy value.
        "multi_select": question.get("multi_select") is True}


def _repair_questions(raw: Any) -> dict[str, Any] | None:
    """Bring an ask_user call's arguments inside the harness's limits.

    :param raw: The tool's raw arguments (a JSON string or an object).
    :return: Repaired arguments, or None when there is nothing honest to
        repair (which re-raises the original error).
    """
    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except ValueError:
            return None
    if not isinstance(parsed, dict):
        return None
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions:
        return None

    seen_headers: set[str] = set()
    repaired = [
        question
        for question in (_repair_question(q, seen_headers) for q in questions)
        if question is not None
    ]
    if not repaired:
        return None
    return {"questions": repaired}


class AskUserRepair(AbstractCapability):
    """Repair ask_user_question arguments instead of failing the turn.

    Registered on the chat agent (and any agent offering the tool),
    because a local model will occasionally write a header the harness
    rejects, and a rejected header should not cost the user the turn.
    """

    @staticmethod
    async def on_tool_validate_error(
        ctx: Any, *, call: Any, tool_def: Any, args: Any, error: Exception
    ) -> dict[str, Any]:
        """Bring a failing ask_user call inside the harness's limits.

        :param ctx: The run context (unused; the repair is context-free).
        :param call: The failing tool call.
        :param tool_def: The tool's definition.
        :param args: The raw arguments that failed validation.
        :param error: The validation error, re-raised when unrepairable.
        :return: The repaired arguments, now valid.
        """
        if getattr(tool_def, "name", "") != ASK_USER_TOOL_NAME:
            raise error
        repaired = _repair_questions(args)
        if repaired is None:
            # Nothing honest to repair: the original error stands, so the
            # model is told what was wrong rather than silently fixed.
            raise error
        logger.info(
            "ask_user_question repaired to fit the harness limits (%d questions)",
            len(repaired["questions"]),
        )
        return repaired
