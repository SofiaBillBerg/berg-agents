"""Guardian Pydantic AI agent for berg_agents.

The Guardian is the gatekeeper of the human-AI balance
principle. It decides when human-in-the-loop review is
needed based on task complexity, risk level, and model
confidence - never "AI does everything".

The Guardian's behavior is defined here, in this module:

- Pattern-based risk assessment (high/medium regex
  lists plus task-type fallback).
- Deterministic HITL decision matrix (critical
  complexity, high risk, low confidence, and
  human-leads / ask-before task types force review).
- Early human-review return: the harness calls
  :func:`guard_review` first and returns its decision
  without invoking the model when review is needed.

The Pydantic AI agent itself (``guardian_agent``) is
used for nuanced cases: it can call the deterministic
``assess_task_risk`` tool and must return a structured
``GuardianDecision``.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
import logging
import re
from typing import Any

from berg_agents.core.interface import RiskLevel, TaskComplexity
from berg_agents.providers.models import resolve_model_instance
from pydantic import BaseModel
from pydantic import Field as PydField
from pydantic_ai import Agent, RunContext

logger = logging.getLogger(__name__)

# Risk patterns for automatic high-risk classification.
HIGH_RISK_PATTERNS: list[str] = [
    r"delete\s+",
    r"remove\s+all",
    r"drop\s+table",
    r"truncate",
    r"rm\s+-rf",
    r"force\s+push",
    r"overwrite",
    r"production",
    r"deploy",
    r"credentials?",
    r"api[_\s]?key",
    r"secret",
    r"password",
    r"token",
    r"security",
    r"auth",
    r"permission",
    r"database\s+migration",
    r"irreversible"]

# Risk patterns for automatic medium-risk classification.
MEDIUM_RISK_PATTERNS: list[str] = [
    r"refactor",
    r"rewrite",
    r"migrate",
    r"upgrade",
    r"downgrade",
    r"install",
    r"uninstall",
    r"configure",
    r"settings?",
    r"environment",
    r"env\s+var"]

# Default HITL task-type gates. Mirror the ``hitl_rules``
# block of ``config/bergagents.jsonc`` (the config is the
# source of truth; these are import-safe fallbacks so the
# pure decision functions never need file access).
AUTO_EXECUTE: list[str] = [
    "read_file",
    "list_files",
    "search_code"]
NOTIFY_AFTER: list[str] = [
    "edit_file",
    "new_file",
    "generate_test"]
ASK_BEFORE: list[str] = [
    "delete_file",
    "execute_command",
    "refactor"]
HUMAN_LEADS: list[str] = [
    "security_change",
    "production_deploy",
    "data_migration"]

# Confidence below this forces human review, whatever
# the risk level says.
LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class GuardianDeps:
    """Dependency bundle injected into the Guardian agent.

    Carries the HITL task-type gates so deployments can
    override them (e.g. from ``hitl_rules`` config)
    without touching module constants.
    """

    auto_execute: list[str] = dc_field(
        default_factory=lambda: list(AUTO_EXECUTE)
    )
    notify_after: list[str] = dc_field(
        default_factory=lambda: list(NOTIFY_AFTER)
    )
    ask_before: list[str] = dc_field(default_factory=lambda: list(ASK_BEFORE))
    human_leads: list[str] = dc_field(default_factory=lambda: list(HUMAN_LEADS))


class GuardianDecision(BaseModel):
    """Structured human-review verdict from the Guardian."""

    needs_human_review: bool = PydField(
        description="True when a human must review/approve."
    )
    risk_level: str = PydField(
        description="Assessed risk: low/medium/high/critical."
    )
    complexity: str = PydField(
        description="Task complexity that fed the decision."
    )
    reasons: list[str] = PydField(
        description="Human-readable reasons for the verdict."
    )
    task_type: str = PydField(description="Task type that was assessed.")


def assess_risk(
    description: str,
    task_type: str = "generic",
) -> RiskLevel:
    """Assess the risk level of a task (pure function).

    Matches the task text against the high/medium risk
    patterns first, then falls back to task-type sets.

    Args:
        description: Free-text task description.
        task_type: Short task-type label.

    Returns:
        The assessed RiskLevel enum value.
    """
    # Combine both signals so patterns match either.
    combined = f"{task_type} {description}".strip()

    # High-risk patterns dominate: check them first.
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return RiskLevel.HIGH

    # Medium-risk patterns only apply when high did not.
    for pattern in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return RiskLevel.MEDIUM

    # Fall back to task-type sets for exact type labels.
    normalized = task_type.lower().strip()
    if normalized in {
        "delete",
        "deploy",
        "security",
        "production",
        "migration"}:
        return RiskLevel.HIGH
    if normalized in {
        "refactor",
        "install",
        "configure",
        "upgrade",
        "rewrite"}:
        return RiskLevel.MEDIUM

    # Default: nothing matched, so low risk.
    return RiskLevel.LOW


def decide_hitl(
    task_type: str,
    complexity: TaskComplexity | str,
    risk: RiskLevel,
    confidence: float = 1.0,
    deps: GuardianDeps | None = None,
) -> tuple[bool, list[str]]:
    """Apply the core HITL decision matrix (pure function).

    Decision matrix:

    - Critical complexity always needs review.
    - High/critical risk always needs review.
    - Low confidence always needs review.
    - Human-leads and ask-before types need review.
    - Everything else auto-executes (notify-after types
      are handled downstream, not as review gates).

    Args:
        task_type: Type of task being assessed.
        complexity: Task complexity level or its value.
        risk: Already-assessed risk level.
        confidence: Model confidence score (0.0 to 1.0).
        deps: Optional HITL gate overrides.

    Returns:
        Tuple of (needs_review, list_of_reasons).

    Raises:
        ValueError: If complexity is unknown or
            confidence is outside 0.0 to 1.0.
    """
    # Validate at the boundary: fail loudly on bad input
    # instead of silently mis-gating a risky task.
    if isinstance(complexity, str):
        complexity = TaskComplexity(complexity)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            f"confidence must be within 0.0 to 1.0, got {confidence!r}."
        )

    # Resolve gate lists from injected deps or defaults.
    gates = deps or GuardianDeps()
    reasons: list[str] = []

    # Critical complexity always needs review.
    if complexity == TaskComplexity.CRITICAL:
        reasons.append("Critical complexity task")

    # High/critical risk always needs review.
    if risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        reasons.append(f"High risk task: {risk.value}")

    # Low confidence always needs review.
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        reasons.append(f"Low model confidence: {confidence:.2f}")

    # Task-type gates from HITL policy.
    if task_type in gates.human_leads:
        reasons.append(f"Human-leads task type: {task_type}")
    elif task_type in gates.ask_before:
        reasons.append(f"Ask-before task type: {task_type}")

    needs_review = len(reasons) > 0
    if not needs_review:
        reasons.append("Auto-execute: low risk, high confidence")

    return needs_review, reasons


def guard_review(
    description: str,
    task_type: str = "generic",
    complexity: TaskComplexity | str = TaskComplexity.STANDARD,
    confidence: float = 1.0,
    deps: GuardianDeps | None = None,
) -> GuardianDecision:
    """Run the deterministic review gate (pure function).

    This is the early-return step of the orchestration
    flow: assess risk, apply the HITL matrix, and return
    the verdict. The harness must return this decision
    to the caller without invoking the model whenever
    ``needs_human_review`` is true.

    Args:
        description: Free-text task description.
        task_type: Short task-type label.
        complexity: Task complexity level or its value.
        confidence: Model confidence score (0.0 to 1.0).
        deps: Optional HITL gate overrides.

    Returns:
        The structured GuardianDecision verdict.
    """
    # Normalize complexity early so the decision below
    # always echoes a valid complexity value string.
    level = (
        TaskComplexity(complexity)
        if isinstance(complexity, str)
        else complexity
    )

    # Deterministic path: no model call, fully testable.
    risk = assess_risk(description, task_type)
    needs_review, reasons = decide_hitl(
        task_type,
        level,
        risk,
        confidence,
        deps,
    )
    return GuardianDecision(
        needs_human_review=needs_review,
        risk_level=risk.value,
        complexity=level.value,
        reasons=reasons,
        task_type=task_type,
    )


# System instructions for the Pydantic AI guardian agent.
# The model handles nuanced cases; the deterministic
# gate above handles the clear-cut early-return path.
_GUARDIAN_INSTRUCTIONS = (
    "You are the Guardian, gatekeeper of the human-AI "
    "balance. Decide when a task needs human review "
    "from risk x complexity x confidence. Call the "
    "assess_task_risk tool before judging risk; never "
    "guess risk levels. High or critical risk, critical "
    "complexity, low confidence, or ask-before / "
    "human-leads task types must return "
    "needs_human_review=true with clear reasons."
)


def build_guardian_agent(
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> Agent[GuardianDeps, GuardianDecision]:
    """Build the Guardian Pydantic AI agent.

    The model is always an explicit OpenAI-compatible instance
    built by :func:`resolve_model_instance` - never a bare id -
    so provider, base URL, and key resolve from the model.

    Args:
        model_id: Model id as declared under a provider
            ``models`` map. None selects the default.
        cfg: Optional config override for resolution.

    Returns:
        A Pydantic AI Agent named "guardian" with the
        risk-assessment tool and structured decisions.
    """
    # Explicit model instance: construction reads config only,
    # never the process environment, and makes no network calls.
    model = resolve_model_instance(model_id, cfg)

    agent: Agent[GuardianDeps, GuardianDecision] = Agent(
        model,
        name="guardian",
        instructions=_GUARDIAN_INSTRUCTIONS,
        deps_type=GuardianDeps,
        output_type=GuardianDecision,
    )

    @agent.tool
    def assess_task_risk(
        ctx: RunContext[GuardianDeps],
        description: str,
        task_type: str = "generic",
    ) -> str:
        """Assess a task's risk level deterministically.

        Args:
            ctx: Run context carrying HITL gate deps.
            description: Free-text task description.
            task_type: Short task-type label.

        Returns:
            Risk level value string.
        """
        # ctx is unused beyond the required first-param
        # slot; assessment is stateless by design. The
        # reference keeps linters quiet about that.
        _ = ctx
        return assess_risk(description, task_type).value

    @agent.tool
    def check_hitl_policy(
        ctx: RunContext[GuardianDeps],
        task_type: str,
    ) -> str:
        """Report the HITL policy gate for a task type.

        Args:
            ctx: Run context carrying HITL gate deps.
            task_type: Short task-type label.

        Returns:
            One of human-leads / ask-before /
            notify-after / auto-execute.
        """
        if task_type in ctx.deps.human_leads:
            return "human-leads"
        if task_type in ctx.deps.ask_before:
            return "ask-before"
        if task_type in ctx.deps.notify_after:
            return "notify-after"
        return "auto-execute"

    return agent


# Default agent instance for the harness.
# Built at import: model string resolution is offline (config only, no network).
# Fallback keeps import safe when default model is not declared.
try:
    guardian_agent: Agent[GuardianDeps, GuardianDecision] = (
        build_guardian_agent()
    )
except Exception:
    guardian_agent = build_guardian_agent(model_id="nemotron-3-nano:30b-cloud")

__all__ = [
    "ASK_BEFORE",
    "AUTO_EXECUTE",
    "HIGH_RISK_PATTERNS",
    "HUMAN_LEADS",
    "LOW_CONFIDENCE_THRESHOLD",
    "MEDIUM_RISK_PATTERNS",
    "NOTIFY_AFTER",
    "GuardianDecision",
    "GuardianDeps",
    "assess_risk",
    "build_guardian_agent",
    "decide_hitl",
    "guard_review",
    "guardian_agent"]
