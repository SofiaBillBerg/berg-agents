"""Subagent implementations for berg_agents.

Import order matters here: ``factory`` must load before ``guardian`` so that
``core.interface`` is fully initialised before the orchestrator (loaded via
``core.harness``) imports from ``agents.guardian`` — otherwise a circular
import bites at module load time.
"""

from __future__ import annotations

from berg_agents.agents.curator import (
    build_update_plan,
    curate_task,
    curation_confidence,
    determine_actions,
    should_run_curator,
)

# Order: factory first (pre-loads core.interface via core.__init__),
# then guardian, implementation, planner, curator.
from berg_agents.agents.factory import (
    DEFAULT_SYSTEM_PROMPT,
    build_agent,
    build_loop,
    create_tools,
)
from berg_agents.agents.guardian import (
    GuardianDecision,
    GuardianDeps,
    assess_risk,
    build_guardian_agent,
    decide_hitl,
    guard_review,
    guardian_agent,
)
from berg_agents.agents.implementation import (
    EXECUTABLE_TASK_TYPES,
    IMPLEMENTATION_AGENT_NAME,
    ComplexityLevel,
    ImplementationDeps,
    PlanStep,
    build_implementation_agent,
    estimate_confidence,
    implementation_agent,
    plan_steps_for,
    resolve_implementation_model,
)
from berg_agents.agents.planner import (
    Planner,
    PlannerDeps,
    Subtask,
    build_plan,
    build_planner_agent,
    decompose,
    estimate_complexity,
    order_subtasks,
    plan_depth,
    planner_agent,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "EXECUTABLE_TASK_TYPES",
    "IMPLEMENTATION_AGENT_NAME",
    "ComplexityLevel",
    "GuardianDecision",
    "GuardianDeps",
    "ImplementationDeps",
    "PlanStep",
    "Planner",
    "PlannerDeps",
    "Subtask",
    "assess_risk",
    "build_agent",
    "build_guardian_agent",
    "build_implementation_agent",
    "build_loop",
    "build_plan",
    "build_planner_agent",
    "build_update_plan",
    "create_tools",
    "curate_task",
    "curation_confidence",
    "decide_hitl",
    "decompose",
    "determine_actions",
    "estimate_complexity",
    "estimate_confidence",
    "guard_review",
    "guardian_agent",
    "implementation_agent",
    "order_subtasks",
    "plan_depth",
    "plan_steps_for",
    "planner_agent",
    "resolve_implementation_model",
    "should_run_curator"]
