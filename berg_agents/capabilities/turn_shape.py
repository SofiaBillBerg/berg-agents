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
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

r"""Turn-shape normalizer: one user turn per model request.

Several strict chat templates reject a conversation that carries two
``user`` turns in a row — Mistral/Devstral's Unsloth template raises
``After the optional system message, conversation roles must alternate
user and assistant roles except for tool calls and results`` and answers
**HTTP 500**, because the check runs inside Jinja rather than as request
validation.

berg's own request shape produces exactly that, for two reasons that only
combine into a failure on strict backends:
1. The harness Memory capability enqueues its ``<memory>`` snapshot with
   ``ctx.enqueue(UserPromptPart(...))``, which lands it **beside** the
   user's own prompt in the same ``ModelRequest`` (a tool call's enqueued
   content rides along with that call's ``ToolReturnPart``, so a steered
   message does the same).
2. pydantic-ai's repair merges adjacent ``ModelRequest``\\ s into one turn
   but keeps each ``UserPromptPart`` separate, and the OpenAI serializer
   emits **one wire message per part** — so two user parts become two
   ``user`` messages.

Permissive backends (ollama, most OpenAI-compatible servers) accept the
shape silently, which is why this never surfaced until a strict template
was pointed at it.

The fix is a history processor (``ProcessHistory``, the documented hook for
exactly this) that coalesces a request's user prompt parts into one,
tool results first. It only merges *text* prompts: a multimodal part is
left untouched rather than flattened, so no image or file is ever lost.
Content is preserved verbatim — the merge joins texts with a blank line —
and the transform is idempotent, so a second pass over already-merged
history changes nothing.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from pydantic_ai import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.capabilities import ProcessHistory

logger = logging.getLogger(__name__)

#: A request needs at least this many user prompt parts before a merge is
#: worth doing — one part is already the shape providers want.
_MIN_USER_PARTS = 2


def _prompt_text(part: UserPromptPart) -> str | None:
    """Text of one user prompt part, or ``None`` when it is multimodal.

    :param part: The user prompt part to read.
    :return: The text when the part is a plain string, else ``None`` —
        a multimodal part carries images or files and must not be
        flattened into text.
    """
    content = part.content
    return content if isinstance(content, str) else None


def _merge_request(message: ModelRequest) -> ModelRequest:
    """Coalesce one request's user prompt parts into a single part.

    Non-prompt parts keep their position; the merged part takes the place
    of the first prompt so tool results still precede it and system
    prompts stay where they were.

    :param message: The request to normalize.
    :return: A normalized copy, or the same object when nothing changed.
    """
    texts = [
        text
        for part in message.parts
        if isinstance(part, UserPromptPart)
        and (text := _prompt_text(part)) is not None
    ]
    if len(texts) < _MIN_USER_PARTS:
        return message
    merged = UserPromptPart(content="\n\n".join(texts))
    parts: list[Any] = []
    placed = False
    for part in message.parts:
        if isinstance(part, UserPromptPart) and _prompt_text(part) is not None:
            if placed:
                continue
            parts.append(merged)
            placed = True
            continue
        parts.append(part)
    # ``replace`` keeps the request's identity (timestamp, instructions,
    # run_id, metadata) so the framework still recognizes it as the same
    # message — required for new_messages() boundary detection.
    return replace(message, parts=parts)


def _fold_user_into_tool_results(message: ModelRequest) -> ModelRequest:
    """Append a request's trailing user text to its last tool result.

    A ``user`` turn sitting directly after a tool result violates the
    strict alternation rule just as two user turns do — and berg produces
    exactly that shape whenever the memory snapshot or a mid-run steer is
    enqueued *with* a tool call's results (pydantic-ai delivers enqueued
    content into the request that carries the call's ``ToolReturnPart``).

    The strict templates render a tool result as one text block, so the
    user's text rides inside it: the content survives verbatim and the
    shape becomes valid. This is the same trade pydantic-ai itself makes
    for a file a tool result carries (``See file {id}`` plus the file on
    the same channel), chosen here for the same reason - the wire format
    has nowhere else to put it.

    :param message: A request holding tool results and user text.
    :return: A normalized copy, or the same object when nothing changed.
    """
    prompts = [
        text
        for part in message.parts
        if isinstance(part, UserPromptPart)
        and (text := _prompt_text(part)) is not None
    ]
    returns = [
        index
        for index, part in enumerate(message.parts)
        if isinstance(part, ToolReturnPart) and isinstance(part.content, str)
    ]
    if not prompts or not returns:
        return message
    carried = "\n\n".join(prompts)
    target = returns[-1]
    parts = list(message.parts)
    original = parts[target]
    parts[target] = replace(
        original, content=f"{original.content}\n\n{carried}"
    )
    # The user turn itself goes: its text now travels with the result.
    parts = [
        part
        for index, part in enumerate(parts)
        if index != target
        and not (
            isinstance(part, UserPromptPart) and _prompt_text(part) is not None
        )
    ]
    return replace(message, parts=parts)


def _merge_adjacent(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Fold an earlier user turn into the request that follows it.

    pydantic-ai coalesces *part-style* enqueues into one request, so the
    shape that survives :func:`_merge_request` is an earlier request
    holding a user prompt followed by a later one that also holds one —
    including the mixed case where the earlier request also carries a
    tool result.

    Text always travels **forward**, into the later request: that is the
    one the current run stamped, so it keeps its identity while the
    earlier request simply loses its prompt parts. A request left with
    nothing at all is dropped — it carries no content — while a request
    that still holds a tool result keeps it, because a tool result must
    stay addressed by its call.

    :param messages: Requests already normalized by :func:`_merge_request`.
    :return: The list with adjacent user turns folded forward.
    """
    out: list[ModelMessage] = []
    index = 0
    while index < len(messages):
        current = messages[index]
        following = messages[index + 1] if index + 1 < len(messages) else None
        if not (
            isinstance(current, ModelRequest)
            and isinstance(following, ModelRequest)
        ):
            out.append(current)
            index += 1
            continue
        carried = [
            text
            for part in current.parts
            if isinstance(part, UserPromptPart)
            and (text := _prompt_text(part)) is not None
        ]
        if not carried:
            out.append(current)
            index += 1
            continue
        target = [
            text
            for part in following.parts
            if isinstance(part, UserPromptPart)
            and (text := _prompt_text(part)) is not None
        ]
        if not target:
            # The next request carries no user turn (tool results only):
            # a lone user turn there is already provider-valid.
            out.append(current)
            index += 1
            continue
        merged_text = "\n\n".join(carried)
        rebuilt: list[Any] = []
        placed = False
        for part in following.parts:
            text = (
                _prompt_text(part) if isinstance(part, UserPromptPart) else None
            )
            if text is None or placed:
                rebuilt.append(part)
                continue
            rebuilt.append(UserPromptPart(content=f"{merged_text}\n\n{text}"))
            placed = True
        # ``replace`` on the *later* request keeps the identity the run
        # stamped on it; the earlier one keeps whatever non-prompt parts
        # it had (a tool result must stay addressable by its call).
        remaining = [
            part
            for part in current.parts
            if not (isinstance(part, UserPromptPart) and _prompt_text(part))
        ]
        if remaining:
            out.append(replace(current, parts=remaining))
        out.append(replace(following, parts=rebuilt))
        index += 2
    return out


def coalesce_user_turns(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Merge each request's user prompt parts so one turn is one message.

    :param messages: The history as the run holds it.
    :return: Normalized history — same content, one user turn per request.
    """
    merged = [
        _fold_user_into_tool_results(m) if isinstance(m, ModelRequest) else m
        for m in messages
    ]
    merged = [
        _merge_request(m) if isinstance(m, ModelRequest) else m for m in merged
    ]
    result = _merge_adjacent(merged)
    if len(result) != len(merged) or any(
        a is not b for a, b in zip(result, merged)
    ):
        logger.info(
            "Turn shape normalized: %d user prompt part(s) merged into one "
            "turn per request (strict chat templates reject two user "
            "turns in a row).",
            sum(len(m.parts) for m in merged)
            - sum(len(m.parts) for m in result),
        )
    return result


def build_turn_shape_capability() -> Any | None:
    """Build the turn-shape normalizer, or ``None`` if unavailable.

    Wrapped in a guard because a capability that cannot be imported must
    not stop the agent from being built: chat keeps working, it just
    keeps the old wire shape.

    :return: A ready ``ProcessHistory`` capability, or ``None``.
    """
    try:
        return ProcessHistory(coalesce_user_turns)
    except Exception as exc:  # pragma: no cover - import-time failure only
        logger.warning("Turn-shape normalizer unavailable: %s", exc)
        return None
