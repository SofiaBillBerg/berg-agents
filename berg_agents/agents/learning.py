"""Learning agent for berg_agents.

Pydantic AI rebuild of the outcome-learning behavior: records
task outcomes, aggregates per-model and per-task-type success
stats, and derives complexity recommendations from evidence.

The outcome-learning behavior is defined here, in this module:

- ``record_outcome`` stores task type, model, success flag.
- ``get_outcome_stats`` aggregates ``total`` /
  ``by_task_type`` / ``by_model`` success-failure counters.
- Insight actions: ``upgrade_complexity`` after a user
  correction, ``review_approach`` on failure, ``reinforce``
  on success.
- Recommendations need at least 3 samples: complexity upgrade
  below a 50 % success rate, complexity downgrade above 90 %
  with at least 5 samples.
- Best-model lookup needs at least 2 samples per model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from berg_agents.providers.models import resolve_model_instance
from pydantic_ai import Agent, RunContext

# Module logger for diagnostics; tools stay side effect free.
logger = logging.getLogger(__name__)

# Explicit agent identity for Logfire run spans (mandatory).
LEARNING_AGENT_NAME = "learning"

# Routing-complexity preference for the learning agent.
PREFERRED_COMPLEXITY = "standard"

# Default model id from config/bergagents.jsonc, used when
# the caller expresses no model preference.
DEFAULT_MODEL_ID = "nemotron-3-nano:30b-cloud"

# Minimum evidence thresholds before stats drive advice.
MIN_SAMPLES_FOR_RECOMMENDATION = 3
MIN_SAMPLES_FOR_DOWNGRADE = 5
MIN_SAMPLES_FOR_BEST_MODEL = 2

# Success-rate boundaries for complexity-change recommendations.
UPGRADE_RATE_BELOW = 0.5
DOWNGRADE_RATE_ABOVE = 0.9

# System instructions for LLM-driven learning runs.
LEARNING_INSTRUCTIONS = (
    "You are the learning agent. Record task outcomes honestly, "
    "summarize what worked, and recommend complexity changes "
    "only when the recorded stats support them."
)

__all__ = [
    "DEFAULT_MODEL_ID",
    "LEARNING_AGENT_NAME",
    "LEARNING_INSTRUCTIONS",
    "PREFERRED_COMPLEXITY",
    "LearningDeps",
    "OutcomeStore",
    "best_model_from_stats",
    "build_learning_agent",
    "build_learning_entry",
    "fetch_best_model",
    "fetch_outcome_stats",
    "fetch_routing_recommendation",
    "generate_recommendation",
    "get_best_model_for_task",
    "get_default_store",
    "get_learnings",
    "get_outcome_stats",
    "learning_agent",
    "recommendation_from_stats",
    "record_outcome",
    "record_task_outcome",
]


@dataclass
class OutcomeStore:
    """Outcome and learning-entry store with SQLite restart survival.

    Stats shape (``total`` / ``by_task_type`` / ``by_model``) stays
    evidence-based for routing advice. Rows persist to the shared
    learning database (see :mod:`berg_agents.core.outcome_db`) so
    a restart reloads history instead of starting from zero.

    Attributes:
        outcomes: Raw recorded outcome dicts in arrival order.
        learnings: Structured learning entries in arrival order.
    """

    outcomes: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[dict[str, Any]] = field(default_factory=list)

    def __init__(
        self,
        outcomes: list[dict[str, Any]] | None = None,
        learnings: list[dict[str, Any]] | None = None,
        db_path: str | None = None,
    ) -> None:
        """Initialize the store, reloading persisted rows when available."""
        from berg_agents.core.outcome_db import ensure, load

        self._db_path = ensure(db_path)
        self.outcomes = (
            list(outcomes)
            if outcomes is not None
            else load(self._db_path, "outcomes")
        )
        self.learnings = (
            list(learnings)
            if learnings is not None
            else load(self._db_path, "learnings")
        )

    def record_outcome(
        self,
        task_type: str,
        model: str,
        success: bool,
        user_corrected: bool = False,
        complexity: str = "standard",
    ) -> dict[str, Any]:
        """Record an outcome and return the learning summary.

        Args:
            task_type: Task-type label for aggregation.
            model: Model identifier that was used.
            success: Whether the task succeeded.
            user_corrected: Whether the user had to correct it.
            complexity: Complexity label stored on the entry.

        Returns:
            Summary dict with ``status``, ``learning``,
            ``stats``, and ``recommendation`` keys.
        """
        # Append the raw outcome before deriving stats so the
        # new sample is included in this call's snapshot.
        outcome = {
            "task_type": task_type,
            "model": model,
            "success": success,
            "user_corrected": user_corrected,
        }
        self.outcomes.append(outcome)
        # Build the structured entry from the same evidence.
        entry = build_learning_entry(
            task_type=task_type,
            complexity=complexity,
            model=model,
            success=success,
            user_corrected=user_corrected,
        )
        self.learnings.append(entry)
        # Persist both rows so a restart reloads this evidence.
        try:
            from berg_agents.core.outcome_db import insert

            insert(self._db_path, "outcomes", outcome)
            insert(self._db_path, "learnings", entry)
        except Exception:
            logger.debug("OutcomeStore persist failed.", exc_info=True)
        logger.debug("Recorded outcome: %s/%s", task_type, model)
        # Snapshot stats after recording for the caller.
        stats = self.get_outcome_stats()
        return {
            "status": "recorded",
            "learning": entry,
            "stats": stats,
            "recommendation": recommendation_from_stats(task_type, stats),
        }

    def get_outcome_stats(self) -> dict[str, Any]:
        """Aggregate success-failure counters per scope.

        Returns:
            Dict with ``total``, ``by_task_type``, and
            ``by_model`` counters, each leaf holding
            ``success`` / ``failure`` counts.
        """
        # Fresh buckets per call so snapshots never alias.
        by_task: dict[str, dict[str, int]] = {}
        by_model: dict[str, dict[str, int]] = {}
        for outcome in self.outcomes:
            # Count once under the task-type scope.
            task_bucket = by_task.setdefault(
                str(outcome.get("task_type", "unknown")),
                {"success": 0, "failure": 0},
            )
            # Count once under the model scope.
            model_bucket = by_model.setdefault(
                str(outcome.get("model", "unknown")),
                {"success": 0, "failure": 0},
            )
            # Success and failure are exclusive tallies.
            if outcome.get("success", False):
                task_bucket["success"] += 1
                model_bucket["success"] += 1
            else:
                task_bucket["failure"] += 1
                model_bucket["failure"] += 1
        return {
            "total": len(self.outcomes),
            "by_task_type": by_task,
            "by_model": by_model,
        }

    def get_learnings(self) -> list[dict[str, Any]]:
        """Return a copy of all recorded learning entries.

        Returns:
            List of learning-entry dicts in arrival order.
        """
        # Copy so callers cannot mutate stored entries.
        return list(self.learnings)

    def get_best_model_for_task(self, task_type: str) -> str | None:
        """Find the best observed model for routing advice.

        Selection is global across models (matching the old
        behavior); ``task_type`` scopes future per-task
        extensions and documents intent.

        Args:
            task_type: Task type the advice is requested for.

        Returns:
            Best performing model name, or None without
            enough evidence.
        """
        _ = task_type  # Reserved for per-task scoping later.
        return best_model_from_stats(self.get_outcome_stats())

    def get_recommendation(self, task_type: str) -> str | None:
        """Recommend a complexity change for a task type, if any.

        Args:
            task_type: Task type to evaluate.

        Returns:
            Recommendation string, or None when evidence is
            thin or the success rate needs no change.
        """
        return recommendation_from_stats(task_type, self.get_outcome_stats())


@dataclass
class LearningDeps:
    """Dependency bundle injected into learning-agent runs.

    Attributes:
        store: Outcome store the tools read and update.
    """

    store: OutcomeStore


def build_learning_entry(
    task_type: str,
    complexity: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
) -> dict[str, Any]:
    """Build a structured learning entry from an outcome.

    Pure function so insight generation stays testable
    without running the agent.

    Args:
        task_type: Task-type label for the entry.
        complexity: Complexity label for the entry.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.

    Returns:
        Learning-entry dict with insight and action.
    """
    # Start from the raw evidence; insight follows below.
    entry: dict[str, Any] = {
        "task_type": task_type,
        "complexity": complexity,
        "model": model,
        "success": success,
        "user_corrected": user_corrected,
    }
    # A user correction outweighs the success flag: the
    # complexity was too low even when the task "succeeded".
    if user_corrected:
        entry["insight"] = (
            f"User correction needed for {task_type} "
            f"with {model}. Consider using a higher-complexity model."
        )
        entry["action"] = "upgrade_complexity"
        entry["type"] = "user_correction"
    elif not success:
        entry["insight"] = (
            f"Task {task_type} failed with {model}. "
            f"Review approach or increase model capability."
        )
        entry["action"] = "review_approach"
        entry["type"] = "failure"
    else:
        entry["insight"] = (
            f"{model} succeeded at {task_type} ({complexity} complexity)."
        )
        entry["action"] = "reinforce"
        entry["type"] = "success"
    return entry


def recommendation_from_stats(
    task_type: str, stats: dict[str, Any]
) -> str | None:
    """Derive a complexity-change recommendation from stats.

    Pure function so thresholds stay testable without
    running the agent.

    Args:
        task_type: Task type to evaluate.
        stats: Outcome-stats dict from ``get_outcome_stats``.

    Returns:
        Recommendation string, or None when evidence is
        thin or the success rate needs no change.
    """
    # Unknown task types carry no evidence to act on.
    by_task = stats.get("by_task_type", {})
    if task_type not in by_task:
        return None
    task_stats = by_task[task_type]
    total = task_stats["success"] + task_stats["failure"]
    # Too few samples to trust the rate either way.
    if total < MIN_SAMPLES_FOR_RECOMMENDATION:
        return None
    success_rate = task_stats["success"] / total
    # Sustained failure means the complexity is likely too low.
    if success_rate < UPGRADE_RATE_BELOW:
        return (
            f"Low success rate ({success_rate:.0%}) for "
            f"{task_type}. Consider upgrading complexity."
        )
    # Sustained success with depth may allow saving cost.
    if (
        success_rate > DOWNGRADE_RATE_ABOVE
        and total >= MIN_SAMPLES_FOR_DOWNGRADE
    ):
        return (
            f"High success rate ({success_rate:.0%}) for "
            f"{task_type}. May downgrade complexity to "
            f"save costs."
        )
    return None


def best_model_from_stats(
    stats: dict[str, Any],
) -> str | None:
    """Pick the highest-rate model with enough evidence.

    Pure function so model selection stays testable
    without running the agent.

    Args:
        stats: Outcome-stats dict from ``get_outcome_stats``.

    Returns:
        Best performing model name, or None without
        enough evidence.
    """
    best_model: str | None = None
    best_rate = -1.0
    for model, model_stats in stats.get("by_model", {}).items():
        total = model_stats["success"] + model_stats["failure"]
        # Skip models with too few observations to trust.
        if total < MIN_SAMPLES_FOR_BEST_MODEL:
            continue
        rate = model_stats["success"] / total
        # Strict comparison keeps the first model on ties.
        if rate > best_rate:
            best_rate = rate
            best_model = model
    return best_model


def record_task_outcome(
    ctx: RunContext[LearningDeps],
    task_type: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
    complexity: str = "standard",
) -> dict[str, Any]:
    """Record a task outcome in the run-scoped store.

    Args:
        ctx: Run context carrying the outcome store.
        task_type: Task-type label for aggregation.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.
        complexity: Complexity label stored on the entry.

    Returns:
        Summary dict with ``status``, ``learning``,
        ``stats``, and ``recommendation`` keys.
    """
    # Delegate to the deps-scoped store so parallel runs
    # stay isolated from each other.
    return ctx.deps.store.record_outcome(
        task_type=task_type,
        model=model,
        success=success,
        user_corrected=user_corrected,
        complexity=complexity,
    )


def fetch_outcome_stats(
    ctx: RunContext[LearningDeps],
) -> dict[str, Any]:
    """Fetch aggregated outcome stats for the run.

    Args:
        ctx: Run context carrying the outcome store.

    Returns:
        Stats dict with ``total``, ``by_task_type``,
        and ``by_model`` counters.
    """
    # Read-only snapshot; never mutates the store.
    return ctx.deps.store.get_outcome_stats()


def fetch_best_model(
    ctx: RunContext[LearningDeps], task_type: str
) -> str | None:
    """Fetch the best observed model for a task type.

    Args:
        ctx: Run context carrying the outcome store.
        task_type: Task type the advice is requested for.

    Returns:
        Best performing model name, or None without
        enough evidence.
    """
    return ctx.deps.store.get_best_model_for_task(task_type)


def fetch_routing_recommendation(
    ctx: RunContext[LearningDeps], task_type: str
) -> str | None:
    """Fetch a complexity-change recommendation, if any.

    Args:
        ctx: Run context carrying the outcome store.
        task_type: Task type to evaluate.

    Returns:
        Recommendation string, or None when evidence is
        thin or no change is needed.
    """
    return ctx.deps.store.get_recommendation(task_type)


def _register_tools(agent: Agent) -> Agent:
    """Register learning tools on an agent instance.

    Each tool takes ``RunContext`` first (the ``@agent.tool``
    contract); the direct-call form below is equivalent to
    decorating each function.

    Args:
        agent: Agent instance to register tools on.

    Returns:
        The same agent instance, for chaining.
    """
    agent.tool(record_task_outcome)
    agent.tool(fetch_outcome_stats)
    agent.tool(fetch_best_model)
    agent.tool(fetch_routing_recommendation)
    return agent


def build_learning_agent(
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> Agent:
    """Create a learning Pydantic AI agent.

    The model is always an explicit OpenAI-compatible instance
    resolved from provider config — never a bare id.
    """
    # Fall back to the default model so callers never
    # have to name a model every time.
    resolved = resolve_model_instance(model_id or DEFAULT_MODEL_ID, cfg)
    # Explicit name= labels this agent's Logfire run span.
    agent = Agent(
        resolved,
        name=LEARNING_AGENT_NAME,
        deps_type=LearningDeps,
        instructions=LEARNING_INSTRUCTIONS,
    )
    return _register_tools(agent)


# Shared module-level agent on the default model.
# The harness drives learning through this instance or builds scoped ones.
# Fallback keeps import safe when default model is not declared.
try:
    learning_agent: Agent = build_learning_agent()
except Exception:
    learning_agent = build_learning_agent(model_id="nemotron-3-nano:30b-cloud")

# Default store backing the module-level sync helpers below.
_default_store = OutcomeStore()


def get_default_store() -> OutcomeStore:
    """Return the module-level default outcome store.

    Returns:
        The shared default ``OutcomeStore`` instance.
    """
    return _default_store


def record_outcome(
    task_type: str,
    model: str,
    success: bool,
    user_corrected: bool = False,
    complexity: str = "standard",
) -> dict[str, Any]:
    """Record an outcome in the default store.

    Sync helper for the harness learning gate, which runs
    without invoking the LLM.

    Args:
        task_type: Task-type label for aggregation.
        model: Model identifier that was used.
        success: Whether the task succeeded.
        user_corrected: Whether the user had to correct it.
        complexity: Complexity label stored on the entry.

    Returns:
        Summary dict with ``status``, ``learning``,
        ``stats``, and ``recommendation`` keys.
    """
    return _default_store.record_outcome(
        task_type=task_type,
        model=model,
        success=success,
        user_corrected=user_corrected,
        complexity=complexity,
    )


def get_outcome_stats() -> dict[str, Any]:
    """Return aggregated stats from the default store.

    Returns:
        Stats dict with ``total``, ``by_task_type``,
        and ``by_model`` counters.
    """
    return _default_store.get_outcome_stats()


def get_learnings() -> list[dict[str, Any]]:
    """Return learning entries from the default store.

    Returns:
        List of learning-entry dicts in arrival order.
    """
    return _default_store.get_learnings()


def get_best_model_for_task(task_type: str) -> str | None:
    """Find the best observed model for a task type.

    Args:
        task_type: Task type the advice is requested for.

    Returns:
        Best performing model name, or None without
        enough evidence.
    """
    return _default_store.get_best_model_for_task(task_type)


def generate_recommendation(task_type: str) -> str | None:
    """Recommend a complexity change for a task type, if any.

    Args:
        task_type: Task type to evaluate.

    Returns:
        Recommendation string, or None when evidence is
        thin or no change is needed.
    """
    return _default_store.get_recommendation(task_type)
