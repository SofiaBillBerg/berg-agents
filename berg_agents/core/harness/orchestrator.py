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

"""Harness orchestrator - the deterministic engine (split from harness.py).

Imports inference and routing helpers from sibling modules. Keeps the public
`Harness` API identical so `from berg_agents.core.harness import Harness` still works.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
import uuid

from berg_agents.agents.curator import curate_task, curation_confidence
from berg_agents.agents.guardian import (
    GuardianDecision,
    GuardianDeps,
    guard_review,
)
from berg_agents.agents.implementation import (
    OUTPUT_RETRIES,
    ImplementationDeps,
    build_implementation_agent,
    estimate_confidence,
    plan_steps_for,
    resolve_implementation_model,
)
from berg_agents.agents.planner import Planner, build_plan, estimate_complexity
from berg_agents.capabilities.registry import ToolCatalog

# Imported helpers (split modules)
from berg_agents.core.harness._inference import (
    _await_inference,
    _files_changed_from_run,
    _files_changed_from_text,
    _finish_reason,
    _inference_prompt,
    _merge_files_changed,
    _ModelUnavailableError,
    _normalize_tool_call_text,
    _render_answer,
    _requested_model_id,
    _usage_dict,
)
from berg_agents.core.harness._routing import (
    _AgentCard,
    _apply_mutation_guard,
    _extract_planned_actions,
    _failed_result,
    _review_gate_result,
    _task_plans_mutation,
)
from berg_agents.core.interface import TaskComplexity
from berg_agents.core.learning_gate import LearningGate
from berg_agents.providers.registry import resolve_model
from pydantic_ai.exceptions import UnexpectedModelBehavior

logger = logging.getLogger(__name__)


class Harness:
    """Deterministic orchestration engine over agent modules.

    Holds the HITL gate overrides, the model-configuration override,
    the agent registry, and the learning gate. All stage
    inputs/outputs are plain dicts so the flow stays testable
    without models or network.
    """

    def __init__(
        self,
        *,
        enable_learning: bool = True,
        enable_inference: bool = False,
        hitl_gates: GuardianDeps | None = None,
        model_cfg: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the harness.

        :param enable_learning: Record outcomes via LearningGate.
        :param enable_inference: Allow synchronous model
                inference on this instance. Approved resumes
                and ungated runs both call the model when True;
                the default False keeps offline runs on
                deterministic templates with
                ``inference_attempted=False``.
        :param hitl_gates: HITL task-type gate overrides; module
                defaults apply when None.
        :param model_cfg: Config override for model resolution;
                live settings apply when None.
        """
        self._enable_learning = enable_learning
        self._enable_inference = enable_inference
        # Fresh default gates per instance so deployments can
        # mutate their copy without touching the module.
        self._gates = hitl_gates or GuardianDeps()
        self._model_cfg = model_cfg
        self._learning_gate = LearningGate()
        self._planner = Planner()
        # Planner is the only AbstractAgent facade; the rest
        # are catalog cards until facades land (later work).
        self._agents: dict[str, Any] = {
            "planner": self._planner,
            "guardian": _AgentCard(
                name="guardian",
                description=(
                    "Decides when human review is needed "
                    "(risk x complexity x confidence)"
                ),
                preferred_complexity="standard",
                capabilities=["risk_assessment", "hitl_policy"],
            ),
            "implementation": _AgentCard(
                name="implementation",
                description=(
                    "Resolves models and execution plans per task type"
                ),
                preferred_complexity="standard",
                capabilities=[
                    "model_resolution",
                    "step_planning",
                    "tool_requirements"],
            ),
            "curator": _AgentCard(
                name="curator",
                description=(
                    "Derives doc and pattern actions from changed files"
                ),
                preferred_complexity="trivial",
                capabilities=["curation", "doc_updates"],
            ),
            "learning": _AgentCard(
                name="learning",
                description="Tracks outcomes and advises routing",
                preferred_complexity="standard",
                capabilities=["outcome_tracking", "routing_advice"],
            )}

    def _chat_bypass_result(
        self,
        *,
        task: dict[str, Any],
        task_type: str,
        description: str,
        complexity: TaskComplexity,
        metadata: dict[str, Any],
        resolved_id: str,
        verdict: GuardianDecision,
        confidence: float,
        planner_score: float,
        impl_score: float,
    ) -> dict[str, Any] | None:
        """Run the direct-model chat bypass when eligible.

        When no mutating tools are planned and inference is
        enabled, guardian/planner/implementation routing is
        skipped and the model runs directly. The chat agent is
        built read-only, so a mutating request without execution
        keywords cannot silently change files.

        :param task: Original task mapping for agent selection.
        :param task_type: Task type label.
        :param description: Human-readable task description.
        :param complexity: Routed complexity.
        :param metadata: Normalized task metadata mapping.
        :param resolved_id: Caller thread id.
        :param verdict: Guardian review verdict (risk reporting only).
        :param confidence: Routing confidence score.
        :param planner_score: Planner self-assessment score.
        :param impl_score: Implementation confidence score.

        :return: Completed result dict when the bypass applies,
            else None to continue normal routing.
        """
        if _task_plans_mutation(task_type, description):
            # Send to planner - never hardcode file paths; planner decides from user's request
            planned = self._plan_mutating_actions(
                task_type=task_type,
                description=description,
                complexity=complexity,
                metadata=metadata,
                resolved_id=resolved_id,
                verdict=verdict,
                confidence=confidence,
                planner_score=planner_score,
                impl_score=impl_score,
            )
            if (
                planned
                and isinstance(planned, list)
                and len(planned) > 0
                and isinstance(planned[0], dict)
                and "args" in planned[0]
            ):
                return {
                    "status": "needs_human_review",
                    "action": planned[0]["action"],
                    "args": planned[0]["args"],
                    "task_id": resolved_id,
                    "review_reasons": [
                        "Proposed: "
                        + planned[0]["args"].get("path", "unknown action")
                    ]}
            return {
                "status": "needs_human_review",
                "action": "unknown",
                "args": {
                    "description": description,
                    "summary": "Planner could not determine file path from request"},
                "task_id": resolved_id,
                "review_reasons": [
                    "No concrete file path proposed by planner for: "
                    + description
                ]}
        if not self._wants_inference(metadata):
            # Must plan concrete actions with real paths - not echo request
            planned = self._plan_mutating_actions(
                task_type=task_type,
                description=description,
                complexity=complexity,
                metadata=metadata,
                resolved_id=resolved_id,
                verdict=verdict,
                confidence=confidence,
                planner_score=planner_score,
                impl_score=impl_score,
            )
            return planned or [
                {
                    "action": task_type,
                    "args": {
                        "description": description,
                        "summary": "planned: " + description[:200],
                        "path": "summary.md"}}
            ]
        logger.info(
            "Task %s direct model interaction: running model directly",
            resolved_id,
        )
        model = resolve_implementation_model(complexity.value, self._model_cfg)
        selected = self._select_agent(task, planner_score, impl_score)
        steps = [step.model_dump() for step in plan_steps_for(task_type)]
        try:
            answer, model_run = self._run_inference(
                description=description,
                task_type=task_type,
                complexity=complexity,
                plan=None,
                steps=steps,
                metadata=metadata,
            )
        except _ModelUnavailableError as exc:
            return _failed_result(
                resolved_id=resolved_id,
                task_type=task_type,
                description=description,
                complexity=complexity,
                verdict=verdict,
                model=model,
                error=str(exc),
                learning_gate=(
                    self._learning_gate if self._enable_learning else None
                ),
            )
        curation = curate_task(
            {
                "task_type": task_type,
                "description": description,
                "complexity": complexity.value},
            _merge_files_changed(
                metadata, model_run.get("files_changed") or []
            ),
        )
        result: dict[str, Any] = {
            "status": "completed",
            "task_id": resolved_id,
            "task_type": task_type,
            "complexity": complexity.value,
            "risk_level": verdict.risk_level,
            "confidence": confidence,
            "selected_agent": selected,
            "model": model_run.get("model_id", model),
            "plan": None,
            "implementation": {
                "steps": steps,
                "tools": ToolCatalog.tools_for(task_type),
                "answer": answer,
                "model_run": model_run},
            "curation": curation,
            "inference_attempted": True}
        if self._enable_learning:
            result["learning"] = self._learning_gate.record(
                {
                    "task_type": task_type,
                    "complexity": complexity.value,
                    "description": description},
                {"success": True, "inference_attempted": True},
                model_used=model_run.get("model_id", model),
                success=True,
            )
        return result

    def execute_task(
        self,
        task: dict[str, Any],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Run one task through guardian to learning.

        The guardian gate returns early on review; planning
        runs for complex/critical tasks only; curation runs
        when ``files_changed`` metadata is present; learning
        records the outcome when enabled. A ``hitl_decision``
        of ``approve`` in ``metadata`` marks a human-approved
        resume: the verdict is still computed for risk
        reporting, but its early-return gate is skipped so
        identical inputs cannot re-gate. A low-confidence-only
        verdict is likewise bypassed when the planned tools
        are all read-only, so conversation proceeds while
        mutating tool calls still pause.

        :param task: Mapping with ``description``, ``task_type``,
                and optional ``metadata`` keys.
        :param task_id: Caller thread id; generated when None.

        :return: Result dict with ``status`` ``completed`` or
            ``needs_human_review`` plus stage outputs.
            ``model`` names the actually-run model: the
            ``model_run.model_id`` when task metadata carries
            an explicit ``requested_model`` override, else
            the complexity default. Under an override the
            complexity default is kept beside it as
            ``complexity_model`` so both labels stay explainable.
        """
        description = str(task.get("description", ""))
        task_type = str(
            task.get("task_type", "implementation") or "implementation"
        )
        metadata = task.get("metadata") or {}
        # Guard against non-mapping metadata from callers.
        if not isinstance(metadata, dict):
            metadata = {}
        # A recorded human approval survives re-execution:
        # resumes carry identical inputs, so the gate must
        # not fire again on them. "edit" counts as approval
        # (the human edited the arguments, then approved).
        approved = metadata.get("hitl_decision") in {"approve", "edit"}
        resolved_id = (
            task_id or str(task.get("task_id", "") or "") or self._new_id()
        )
        complexity = estimate_complexity(description, task_type)
        # Both routing signals are pure; the stronger one
        # feeds the guardian confidence check below.
        planner_score = self._planner.can_handle(task)
        impl_score = estimate_confidence(task_type, description)
        confidence = max(planner_score, impl_score)
        verdict = guard_review(
            description,
            task_type,
            complexity,
            confidence,
            self._gates,
        )
        # Mutating tool calls always pause for approval; see
        # _apply_mutation_guard for the exact rules.
        verdict = _apply_mutation_guard(verdict, task_type, description)
        # Chat bypass: when no mutating tools are planned and
        # inference is enabled, skip guardian/planner/
        # implementation routing and run the model directly
        # (see _chat_bypass_result).
        bypassed = self._chat_bypass_result(
            task=task,
            task_type=task_type,
            description=description,
            complexity=complexity,
            metadata=metadata,
            resolved_id=resolved_id,
            verdict=verdict,
            confidence=confidence,
            planner_score=planner_score,
            impl_score=impl_score,
        )
        if bypassed is not None:
            return bypassed
        # Plan-then-gate: before pausing a mutating task for
        # human review, ask the model (read-only, nothing is
        # executed) to declare the concrete actions it intends -
        # real file paths instead of the ToolCatalog placeholder
        # echo. The HITL card then shows what will truly happen,
        # and approve/edit operate on real arguments.
        planned_actions: list[dict[str, Any]] | None = None
        if (
            verdict.needs_human_review
            and not approved
            and self._wants_inference(metadata)
            and _task_plans_mutation(task_type, description)
        ):
            planned_actions = self._plan_mutating_actions(
                description=description,
                task_type=task_type,
                complexity=complexity,
                metadata=metadata,
            )
        # Early return: a human must review before anything
        # else runs (see _review_gate_result); approved resumes
        # and read-only low-confidence verdicts proceed.
        gated = _review_gate_result(
            verdict=verdict,
            task_type=task_type,
            description=description,
            resolved_id=resolved_id,
            confidence=confidence,
            approved=approved,
            action_requests=planned_actions,
        )
        if gated is not None:
            return gated
        # Planning is reserved for work that needs it;
        # trivial/standard tasks skip straight to routing.
        plan: dict[str, Any] | None = None
        if complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
            plan = build_plan(description, task_type, complexity)
        # Ensure plan carries concrete actions (functional, not decorative)
        # Ensure COMPLEX/CRITICAL plan carries concrete steps; empty plan filled with step template.if plan is not None and (plan.get("steps") is None or not plan.get("steps")):
        plan["steps"] = (
            [step.model_dump() for step in plan_steps_for(task_type)]
            if not plan.get("steps")
            else plan.get("steps")
        )
        # Complexity maps directly onto its model id,
        # and the resolver always adds the provider prefix.
        model = resolve_implementation_model(complexity.value, self._model_cfg)
        selected = self._select_agent(task, planner_score, impl_score)
        # Deterministic implementation surface: the step
        # template and tool list the runner will consume.
        steps = [step.model_dump() for step in plan_steps_for(task_type)]
        implementation = {
            "steps": steps,
            "tools": ToolCatalog.tools_for(task_type)}
        # Synchronous model inference. The gate path returned
        # above, so reaching here means completed-or-failed,
        # never a re-gate: approved resumes and ungated runs
        # alike infer whenever this instance allows it.
        inference_attempted = self._wants_inference(metadata)
        # Truthful result label: the complexity default stands
        # until an explicit override proves another model
        # ran (see the ``model_run`` reconciliation below).
        requested_override: str | None = None
        effective_model = model
        # Bound for the no-inference path below: curation reads
        # model_run for observed files, and an empty run means
        # no observed files rather than an unbound name.
        model_run: dict[str, Any] = {}
        if inference_attempted:
            try:
                answer: str
                model_run: dict[str, Any]
                answer, model_run = self._run_inference(
                    description=description,
                    task_type=task_type,
                    complexity=complexity,
                    plan=plan,
                    steps=steps,
                    metadata=metadata,
                )
            except _ModelUnavailableError as exc:
                return _failed_result(
                    resolved_id=resolved_id,
                    task_type=task_type,
                    description=description,
                    complexity=complexity,
                    verdict=verdict,
                    model=model,
                    error=str(exc),
                    learning_gate=(
                        self._learning_gate if self._enable_learning else None
                    ),
                )
            implementation["answer"] = answer
            implementation["model_run"] = model_run
            # Reconcile the result label with the actually-run
            # model: an explicit ``requested_model`` override
            # wins over complexity routing, so the label must name
            # ``model_run.model_id``. Without an override the
            # complexity default is kept beside it as
            # ``complexity_model`` so both labels stay explainable.
            requested_override = _requested_model_id(metadata)
            if requested_override is not None:
                effective_model = str(model_run.get("model_id") or model)
        # Deterministic offline fallback (no phrase
        # matching): with inference disabled the model
        # never ran, so chat-mode tasks would complete
        # with no answer at all. Mutating tasks keep
        # their steps/tools surface; chat just notes
        # offline mode and how to enable live answers.
        elif not _task_plans_mutation(task_type, description):
            implementation["answer"] = (
                "Hello! I'm Berg Agents, running offline "
                "(inference is disabled), so I can't "
                "generate a live answer. Enable inference "
                "or set run_model for a live answer."
            )
        # Curator self-gates on files_changed metadata.
        curation = curate_task(
            {
                "task_type": task_type,
                "description": description,
                "complexity": complexity.value},
            _merge_files_changed(
                metadata, model_run.get("files_changed") or []
            ),
        )
        result: dict[str, Any] = {
            "status": "completed",
            "task_id": resolved_id,
            "task_type": task_type,
            "complexity": complexity.value,
            "risk_level": verdict.risk_level,
            "confidence": confidence,
            "selected_agent": selected,
            "model": effective_model,
            "plan": plan,
            "implementation": implementation,
            "curation": curation,
            "inference_attempted": inference_attempted}
        if requested_override is not None:
            # Routing label kept beside the truthful one:
            # what complexity routing chose before the
            # session override won (routes active model).
            result["complexity_model"] = model
        # Learning observes successes only; gated tasks never
        # executed, so recording them would skew the stats.
        if self._enable_learning:
            insight = self._learning_gate.record(
                {
                    "task_type": task_type,
                    "complexity": complexity.value,
                    "description": description},
                {"success": True, "inference_attempted": inference_attempted},
                model_used=effective_model,
                success=True,
            )
            result["learning"] = insight
        return result

    def _wants_inference(self, metadata: dict[str, Any]) -> bool:
        """Decide whether this run performs model inference.

        Inference runs when the instance allows it via
        ``enable_inference`` or the task opts in with
        ``metadata["run_model"]``. The gate path returns
        before this is consulted, so gated tasks never infer.

        :param metadata: Normalized task metadata mapping.

        :return:        True when the implementation agent should run.
        """
        if self._enable_inference:
            return True
        return metadata.get("run_model") is True

    def _plan_mutating_actions(
        self,
        *,
        description: str,
        task_type: str,
        complexity: TaskComplexity,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Ask the model (read-only) what mutating actions it intends.

        Runs a planning inference with no mutating tools registered:
        the model declares its concrete tool calls - real file paths
        and a one-line summary - as a JSON array. The caller shows
        these on the HITL card so the human approves the *actual*
        plan, not a placeholder echo of their request. On any
        failure this returns None and the gate falls back to the
        deterministic placeholder actions.

        :param description: Task description for the prompt.
        :param task_type: Task type for deps.
        :param complexity: Routed complexity driving the model.
        :param metadata: Task metadata carrying any model override.

        :return:        Normalized action list ``[{"action": name,
            "args": {...}}, ...]``, or None when planning failed.
        """
        if not self._wants_inference(metadata):
            # Fallback when inference disabled: return concrete planned actions so HITL shows real steps (fix: was dict, needs list)
            return [
                {
                    "action": task_type,
                    "args": {
                        "description": description,
                        "summary": "planned: " + description[:200],
                        "file": "summary.md"}}
            ]
        requested = _requested_model_id(metadata)
        try:
            agent = build_implementation_agent(
                complexity=complexity.value,
                model_id=requested,
                cfg=self._model_cfg,
                instructions=(
                    "You are a planning assistant. Read the user's request, decide exact real file paths to write/edit/delete, respond ONLY a JSON array with tool/path/summary. Do NOT echo description as summary. No prose."
                ),
                read_only=True,
            )
            prompt = (
                f"Task: {description}\n\nDeclare the exact mutating "
                "tool actions for this task. JSON array only."
            )
            deps = ImplementationDeps(
                task_type=task_type, complexity=complexity.value
            )
            run_result = asyncio.run(_await_inference(agent, prompt, deps))
        except Exception as exc:
            logger.warning(
                "Mutation planning inference failed; "
                "falling back to placeholder actions: %s",
                exc,
            )
            return {
                "status": "needs_human_review",
                "action": task_type,
                "args": {
                    "description": description,
                    "summary": "planned: " + description[:200]}}
        return _extract_planned_actions(getattr(run_result, "output", ""))

    def _run_inference(
        self,
        *,
        description: str,
        task_type: str,
        complexity: TaskComplexity,
        plan: dict[str, Any] | None,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Run the implementation agent synchronously.

        The explicit model override in
        ``metadata["requested_model"]`` wins; otherwise the
        complexity default (then the registry default) applies via
        ``build_implementation_agent``. Must run in a
        synchronous context (CLI, worker thread, tests) -
        never from a running event loop.


        :param description: Task description for the prompt.
        :param task_type: Task type for deps and prompt.
        :param complexity: Routed complexity driving the model.
        :param plan: Planner output, if any, for prompt context.
        :param steps: Deterministic step templates for context.
        :param metadata: Task metadata carrying the override.

        :return:        ``(answer, model_run)`` with displayable answer
            text and run metadata. A final
            ``UnexpectedModelBehavior`` (output validation
            exhausted) falls back to the normalized plain-text
            body via ``_render_answer`` instead of failing, so
            callers still complete with ``inference_attempted``
            True and learning recorded.

        :raises:
            _ModelUnavailableError: On unknown models,
                build failures, connection/model errors,
                timeouts, or empty answers.
        """
        requested = _requested_model_id(metadata)
        try:
            resolved = resolve_model(requested, self._model_cfg)
        except KeyError as exc:
            raise _ModelUnavailableError(
                f"model_unavailable: unknown model {requested!r} ({exc})"
            ) from exc
        base_url = str(resolved.get("base_url") or "unknown")
        provider = str(resolved.get("_provider") or "unknown")
        model_name = str(resolved.get("model") or requested or "unknown")
        chat_mode = not _task_plans_mutation(task_type, description)
        chat_instructions = (
            (
                "You are Berg Agents, a friendly, helpful AI coding assistant and conversational partner. "
                "Answer the user's question, greeting, or message naturally, clearly, and conversationally. "
                "Do not execute file changes or use file-editing tools unless specifically requested. "
                "NEVER generate greetings, salutations, or filler prose - a greeting wastes tokens and "
                "provides no value. Respond with a single brief acknowledgment, then ask what the user needs."
            )
            if chat_mode
            else None
        )

        try:
            # Chat mode runs a read-only agent: no mutating tools
            # are registered, so the model cannot change files
            # without going through the HITL gate above.
            agent = build_implementation_agent(
                complexity=complexity.value,
                model_id=requested,
                cfg=self._model_cfg,
                instructions=chat_instructions,
                read_only=chat_mode,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise _ModelUnavailableError(
                f"model_unavailable: cannot build model "
                f"{model_name!r} (base_url={base_url}): {exc}"
            ) from exc
        prompt = _inference_prompt(
            description=description,
            task_type=task_type,
            complexity=complexity,
            plan=plan,
            steps=steps,
        )
        deps = ImplementationDeps(
            task_type=task_type, complexity=complexity.value
        )
        start = time.perf_counter()
        # Harness-level output retries mirror the agent budget
        # (OUTPUT_RETRIES): fakes in tests raise UMB directly
        # without pydantic-ai's internal retry, so the harness
        # retries here; a final UMB falls back to plain text
        # instead of failing loudly.
        last_unexpected: UnexpectedModelBehavior | None = None
        run_result: Any = None
        for _ in range(OUTPUT_RETRIES + 1):
            try:
                run_result = asyncio.run(_await_inference(agent, prompt, deps))
                last_unexpected = None
                break
            except UnexpectedModelBehavior as exc:
                last_unexpected = exc
                continue
            except Exception as exc:
                raise _ModelUnavailableError(
                    f"model_unavailable: inference failed for "
                    f"{model_name!r} (base_url={base_url}): "
                    f"{exc.__class__.__name__}: {exc}"
                ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        if last_unexpected is not None:
            # Output validation exhausted: complete with the
            # normalized plain-text body, not a failure. The
            # normalizer runs before this render so separator
            # variants are fixed before validation below.
            raw_body = last_unexpected.body or last_unexpected.message or ""
            answer = _render_answer(_normalize_tool_call_text(str(raw_body)))
            # Ensure retry-exhausted result is visible, not empty
            if not answer.strip():
                answer = "[Model retry exhausted - no output produced after retries. Check model/connection.]"
            if not answer.strip():
                raise _ModelUnavailableError(
                    f"model_unavailable: empty answer from "
                    f"{model_name!r} (base_url={base_url})"
                )
            model_run = {
                "model_id": model_name,
                "provider": provider,
                "base_url": base_url,
                "complexity": complexity.value,
                "latency_ms": latency_ms,
                "usage": {},
                "finish_reason": "output_retry_exhausted",
                "fallback": "plain_text",
                "files_changed": []}
            return answer, model_run
        raw_output = getattr(run_result, "output", run_result)
        # Separator-tolerant normalization before validation:
        # text outputs with a missing/odd ``call:`` separator
        # are fixed here so validation sees canonical form.
        if isinstance(raw_output, str):
            raw_output = _normalize_tool_call_text(raw_output)
        answer = _render_answer(raw_output)
        if not answer.strip():
            raise _ModelUnavailableError(
                f"model_unavailable: empty answer from "
                f"{model_name!r} (base_url={base_url})"
            )
        model_run = {
            "model_id": model_name,
            "provider": provider,
            "base_url": base_url,
            "complexity": complexity.value,
            "latency_ms": latency_ms,
            "usage": _usage_dict(run_result),
            "finish_reason": _finish_reason(run_result),
            "files_changed": _files_changed_from_run(run_result)
            or _files_changed_from_text(answer)}
        return answer, model_run

    @staticmethod
    def _select_agent(
        task: dict[str, Any],
        planner_score: float,
        impl_score: float,
    ) -> str:
        """Pick the executor from confidence scores.

        Scores come from the planner facade and the
        implementation/curator confidence functions. A sole
        winner takes the task; ties (or a curator-only win
        on curation-typed tasks aside) fall back to the
        default implementation executor per the spec.

        :param task: Task mapping being routed.
        :param planner_score: Precomputed planner confidence.
        :param impl_score: Precomputed implementation score.

        :return:        Selected registry name.
        """
        scores = {
            "planner": planner_score,
            "implementation": impl_score,
            "curator": curation_confidence(task)}
        best = max(scores.values())
        winners = [name for name, s in scores.items() if s == best]
        # Ties mean no executor clearly owns the task, so the
        # default implementation executor takes it.
        if len(winners) == 1:
            return winners[0]
        return "implementation"

    def get_agent(self, name: str) -> Any:
        """Return one registry entry by name.

        :param name: Registered agent name.

        :return:        The agent facade or catalog card.

        :raises KeyError: When no agent has that name.
        """
        try:
            return self._agents[name]
        except KeyError:
            raise KeyError(f"Unknown agent '{name}'") from None

    def get_agent_info(self) -> list[dict[str, Any]]:
        """List catalog info for all registered agents.

        :return: Info mappings in registration order.
        """
        infos: list[dict[str, Any]] = []
        for name, agent in self._agents.items():
            get_info = getattr(agent, "get_info", None)
            # Custom agents follow the contract; anything
            # else still yields a minimal catalog entry.
            info: Any = get_info() if callable(get_info) else {"name": name}
            if isinstance(info, dict):
                infos.append(info)
            else:
                infos.append({"name": name})
        return infos

    def register_agent(self, name: str, agent: Any) -> None:
        """Register a custom agent facade.

        :param   name: Registry key for the agent.
        :param agent: Agent implementing the contract.
        """
        self._agents[name] = agent

    def get_learning_stats(self) -> dict[str, Any]:
        """Return learning/outcome statistics.

        :return: Stats mapping with outcome counters plus
            insight and adjustment tallies.
        """
        return self._learning_gate.get_stats()

    @staticmethod
    def _new_id() -> str:
        """Generate a short hex id for id-less tasks.

        :return: 12-char hex string.
        """
        return uuid.uuid4().hex[:12]
