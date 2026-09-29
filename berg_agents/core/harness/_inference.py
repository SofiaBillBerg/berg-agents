"""Inference helpers for Harness (split from harness.py).

The Harness is the canonical task-execution engine. It wires the
Pydantic AI agent modules into one deterministic flow:

1. Guardian ``guard_review`` risk/HITL gate with early return.
2. Planner ``build_plan`` decomposition for complex/critical work.
3. Model selection via ``resolve_implementation_model`` (provider
   prefix always comes from config, never a global flag).
4. Agent selection from ``can_handle``/confidence scores, with
    implementation as the default executor.
5. Synchronous implementation-agent inference whenever the
    instance allows it (approved resumes and ungated runs
    alike); otherwise deterministic templates only.
6. Curator ``curate_task`` step when ``files_changed`` metadata
   is present.
7. Learning outcome recording through ``LearningGate`` when
   enabled (failures recorded with ``success=False``).

The web layer (``ui.server``/``ui.routes``) and ``app.py`` depend
only on the small method surface below: ``execute_task``,
``get_agent``/``get_agent_info``/``register_agent``, and
``get_learning_stats``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
from typing import Any

from berg_agents.agents.implementation import ImplementationDeps
from berg_agents.core.interface import TaskComplexity

logger = logging.getLogger(__name__)

__all__ = ["Harness"]

#: Per-call timeout (seconds) for synchronous model inference.
#: The registry default (``6000000``ms in bergagents.jsonc) is
#: effectively infinite, so inference never inherits it — this
#: explicit bound applies instead.
_INFERENCE_TIMEOUT_S = 90.0


class _ModelUnavailableError(Exception):
    """Loud failure for synchronous model inference.

    Raised instead of returning silent template output when the
    model cannot be reached, rejects the request, is unknown to
    the registry, or returns an empty answer. Callers convert it
    to a ``failed`` result dict carrying a ``model_unavailable:``
    error message.
    """


def _requested_model_id(metadata: dict[str, Any]) -> str | None:
    """Return the explicit model override from task metadata.

    Args:
        metadata: Normalized task metadata mapping.

    Returns:
        Non-empty ``requested_model`` string, else None (the
        complexity default, then the registry default, applies).
    """
    requested = metadata.get("requested_model")
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    return None


def _inference_prompt(
    *,
    description: str,
    task_type: str,
    complexity: TaskComplexity,
    plan: dict[str, Any] | None,
    steps: list[dict[str, Any]],
) -> str:
    """Render the task prompt for the implementation agent.

    Carries the description, type, complexity, plan context,
    and deterministic step templates so the model sees
    exactly what the harness routed.

    Args:
        description: Task description.
        task_type: Task type label.
        complexity: Routed complexity.
        plan: Planner output, if any.
        steps: Deterministic step templates.

    Returns:
        Plain-text prompt for the agent run.
    """
    lines = [
        f"Task: {description}",
        f"task_type={task_type} complexity={complexity.value}"]
    if plan:
        lines.append(f"plan={plan}")
    if steps:
        names = [
            str(step.get("action", "?"))
            for step in steps
            if isinstance(step, dict)
        ]
        lines.append("steps=" + ", ".join(names))
    return "\n".join(lines)


async def _await_inference(
    agent: Any, prompt: str, deps: ImplementationDeps
) -> Any:
    """Run one implementation-agent call under an explicit timeout.

    Args:
        agent: Built implementation agent.
        prompt: Fully rendered task prompt.
        deps: Per-run implementation dependencies.

    Returns:
        The Pydantic AI run result.

    Raises:
        asyncio.TimeoutError: When the model call exceeds
            ``_INFERENCE_TIMEOUT_S``.
    """
    return await asyncio.wait_for(
        agent.run(prompt, deps=deps), timeout=_INFERENCE_TIMEOUT_S
    )


#: Tool names whose calls count as touching a file.
_FILE_TOUCHING_TOOLS: frozenset[str] = frozenset(
    {
        "write_file",
        "edit_file"}
)

#: Tool-argument keys carrying the touched path, in priority order.
_FILE_PATH_ARG_KEYS: tuple[str, ...] = ("file_path", "path")


def _files_changed_from_run(run_result: Any) -> list[str]:
    """Collect file paths touched by mutating tool calls in a run.

    Walks the Pydantic AI run messages for ``write_file`` /
    ``edit_file`` calls and returns their target paths in call
    order, deduplicated. Fully defensive: fakes and partial
    results without messages yield an empty list instead of
    raising, so inference callers never break on this.

    Args:
        run_result: Pydantic AI run result (or test fake).

    Returns:
        Ordered, deduplicated list of touched file paths.
    """
    messages: list[Any] = []
    for accessor in ("new_messages", "all_messages"):
        getter = getattr(run_result, accessor, None)
        if not callable(getter):
            continue
        try:
            fetched: Any = getter() or []
            messages = list(fetched)
        except Exception:
            logger.debug("Ignoring unreadable run messages.", exc_info=True)
            continue
        if messages:
            break
    touched: list[str] = []
    seen: set[str] = set()
    for message in messages:
        parts = getattr(message, "parts", None) or []
        for part in parts:
            if isinstance(part, dict):
                name = part.get("tool_name")
                args = part.get("args")
            else:
                name = getattr(part, "tool_name", None)
                args = getattr(part, "args", None)
            if not isinstance(name, str) or name not in _FILE_TOUCHING_TOOLS:
                continue
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, TypeError):
                    continue
            if not isinstance(args, dict):
                continue
            for key in _FILE_PATH_ARG_KEYS:
                value = args.get(key)
                if (
                    isinstance(value, str)
                    and value.strip()
                    and value not in seen
                ):
                    seen.add(value)
                    touched.append(value)
                    break
    return touched


#: Regex matching a write_file JSON shape embedded in model text.
#: Handles both plain JSON (``"name"``) and escaped form
#: (``\"name\"``) that some models produce when emitting tool-call
#: text as a string rather than a structured tool call.
_WRITE_FILE_RE = re.compile(
    r'\\?"name\\?"\s*:\s*"?write_file"?\s*,\s*'
    r'\\?"arguments\\?"\s*:\s*\{[^}]*'
    r'\\?"path\\?"\s*:\s*"([^"]+)"[^}]*\}',
    re.DOTALL,
)


def _files_changed_from_text(text: str) -> list[str]:
    r"""Extract write_file paths from model answer text.

    When the model produces text containing a JSON tool-call
    shape (e.g. ``{"name": "write_file", "arguments": {"path": "..."}}``)
    rather than a structured Pydantic AI tool call, this fallback
    parses the text and returns the touched paths.

    Handles both clean JSON and escaped (``\\\"name\\\"``) forms,
    and also parses the text as JSON if it is a JSON string.

    :param text: Model answer text (possibly containing JSON).
    :return: Ordered, deduplicated list of touched file paths.
    """
    seen: set[str] = set()
    touched: list[str] = []

    # Try treating the whole text as a JSON value first —
    # handles escaped-string model outputs.
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        args = parsed.get("arguments") or parsed.get("args") or {}
        path = args.get("path") if isinstance(args, dict) else None
        if isinstance(path, str) and path.strip() and path not in seen:
            seen.add(path)
            touched.append(path)

    # Regex fallback: find write_file shapes anywhere in the text,
    # including escaped form (\\") produced by some models.
    for match in _WRITE_FILE_RE.finditer(text):
        path = match.group(1)
        if path and path not in seen:
            seen.add(path)
            touched.append(path)

    return touched


def _merge_files_changed(
    metadata: dict[str, Any], observed: list[str]
) -> dict[str, Any]:
    """Copy metadata with run-observed paths merged into files_changed.

    Caller-provided entries come first; observed paths are
    appended deduplicated. The caller's mapping is never
    mutated — curation gets its own copy.

    Args:
        metadata: Normalized task metadata mapping.
        observed: Paths extracted from the inference run.

    Returns:
        New metadata mapping for the curation step.
    """
    merged: dict[str, Any] = dict(metadata)
    if not isinstance(observed, list):
        observed = []
    existing = merged.get("files_changed")
    paths: list[str] = [
        str(path)
        for path in (existing if isinstance(existing, list) else [])
        if isinstance(path, str) and path.strip()
    ]
    for path in observed:
        if path not in paths:
            paths.append(path)
    if paths:
        merged["files_changed"] = paths
    return merged


def _render_answer(output: Any) -> str:
    """Render an agent output as displayable answer text.

    Structured implementation outputs become a short status
    line plus their execution-plan steps; plain strings pass
    through; anything else is stringified.

    Args:
        output: Run output (structured result or text).

    Returns:
        Displayable answer string (possibly empty).
    """
    if isinstance(output, str):
        return output
    steps = getattr(output, "execution_plan", None)
    status = getattr(output, "status", None)
    if isinstance(steps, list) and steps:
        lines = [f"status={status}"] if status else []
        for pos, step in enumerate(steps, 1):
            action = getattr(step, "action", "?")
            desc = getattr(step, "description", "")
            lines.append(f"{pos}. [{action}] {desc}".rstrip())
        return "\n".join(lines).strip()
    model_dump = getattr(output, "model_dump_json", None)
    if callable(model_dump):
        dumped = model_dump(indent=2)
        if isinstance(dumped, str):
            return dumped
    return str(output)


#: Lines starting with a ``call`` prefix (colon optional,
#: case-insensitive) treated as tool-call text for normalization.
_TOOL_CALL_PREFIX_RE = re.compile(r"(?i)^\s*call\s*:?\s*(.*?)\s*$")


def _normalize_tool_call_text(text: str) -> str:
    """Normalize tool-call text before validation.

    Tolerates a missing ``call:`` separator and whitespace
    variants (case, spacing around the colon, collapsing
    internal runs), following the tolerant-parsing precedent
    in :mod:`berg_agents.core.loop` (``_extract_tool_calls``
    accepts JSON-string args, missing ids, and the Anthropic
    shape instead of rejecting variants). Non-call lines pass
    through with surrounding whitespace stripped.

    Args:
        text: Raw model text (possibly multi-line).

    Returns:
        Normalized text with ``call:``-prefixed lines in
        canonical ``"call: <args>"`` form.
    """
    # Non-strings cannot carry the separator variant; the
    # caller stringifies them via _render_answer instead.
    if not isinstance(text, str):
        return text
    normalized: list[str] = []
    for line in text.splitlines() or [""]:
        match = _TOOL_CALL_PREFIX_RE.match(line)
        # Only rewrite lines that actually carry the prefix;
        # anything else keeps its content (stripped).
        if match and match.group(1):
            # Collapse internal whitespace so alignment
            # variants compare equal downstream.
            rest = " ".join(match.group(1).split())
            normalized.append(f"call: {rest}")
        else:
            normalized.append(line.strip())
    return "\n".join(normalized).strip()


def _usage_dict(run_result: Any) -> dict[str, Any]:
    """Extract token usage from a run result, the best effort.

    Args:
        run_result: Pydantic AI run result.

    Returns:
        Usage mapping; empty when unavailable.
    """
    usage = getattr(run_result, "usage", None)
    raw = usage() if callable(usage) else usage
    if raw is None:
        return {}
    if dataclasses.is_dataclass(raw) and not isinstance(raw, type):
        try:
            dumped: Any = dataclasses.asdict(raw)
        except Exception:
            dumped = None
        if isinstance(dumped, dict):
            return dumped
    out: dict[str, Any] = {}
    for key in ("requests", "input_tokens", "output_tokens"):
        val = getattr(raw, key, None)
        if val is not None:
            out[key] = val
    return out


def _finish_reason(run_result: Any) -> str:
    """Extract the finish reason from a run result, the best effort.

    Args:
        run_result: Pydantic AI run result.

    Returns:
        Finish-reason string, or ``"unknown"``.
    """
    direct = getattr(run_result, "finish_reason", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    nested = getattr(
        getattr(run_result, "response", None), "finish_reason", None
    )
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return "unknown"


# noinspection unresolved-references
