"""Core framework-agnostic orchestrator for the berg_agents package.

The Orchestrator is the central control point. It:
1. Registers all native subagents (guardian, planner, implementation, curator, learning)
2. Discovers plugins from bergagents.jsonc paths
3. Routes tasks to the right agent based on can_handle() confidence
4. Executes the full task execution workflow with HITL integration
5. Feeds the Learning Gate for adaptive improvement

This module does NOT depend on LangGraph, LangChain, or any LLM framework.
"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any
import uuid

from berg_agents.agents.curator import Curator
from berg_agents.agents.guardian import Guardian
from berg_agents.agents.implementation import Implementation
from berg_agents.agents.learning import Learning
from berg_agents.agents.planner import Planner
from berg_agents.core.interface import (
    AbstractAgent,
    TaskComplexity,
    TaskContext,
)
from berg_agents.core.model_router import ModelRouter

logger = logging.getLogger(__name__)


class Orchestrator:
    """Discovers agents, routes tasks, and executes workflows.

    The orchestrator coordinates all subagents:
    - Guardian: decides HITL needs
    - Planner: decomposes complex tasks
    - Implementation: executes code changes
    - Curator: updates documentation
    - Learning: records outcomes and adapts routing

    It supports both native agents (built-in) and plugin agents
    (loaded from bergagents.jsonc paths).
    """

    def __init__(
        self,
        plugins: Iterable[Any] | None = None,
        *,
        router: ModelRouter | None = None,
        enable_learning: bool = True,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            plugins: Optional paths to plugin agent directories.
            router: Optional custom ModelRouter instance.
            enable_learning: Whether to enable the learning gate.
        """
        self.router = router or ModelRouter()
        self.enable_learning = enable_learning
        self._plugins: list[Any] = list(plugins or [])

        # Core framework-agnostic subagents
        self._guardian = Guardian()
        self._planner = Planner(router=self.router)
        self._implementation = Implementation(router=self.router)
        self._curator = Curator()
        self._learning = Learning(router=self.router)

        # Agent registry — maps name -> agent instance
        self._agents: dict[str, AbstractAgent] = {
            "guardian": self._guardian,
            "planner": self._planner,
            "implementation": self._implementation,
            "curator": self._curator,
            "learning": self._learning,
        }

        # Legacy registry for backwards compat (tests expect orch.registry)
        self.registry: dict[str, list[dict[str, Any]]] = {
            "agents": [],
            "workflows": [],
        }
        # Plugin agents (loaded dynamically — legacy registry.json support + new agents)
        self._plugin_agents: dict[str, Any] = {}
        # Legacy plugin loading: if a plugin dir has registry.json, load it for backwards compat
        for plugin_path in self._plugins:
            try:
                import json
                from pathlib import Path

                reg_file = Path(plugin_path) / "registry.json"
                if reg_file.exists():
                    data = json.loads(reg_file.read_text(encoding="utf-8"))
                    self.registry["agents"].extend(data.get("agents", []))
                    self.registry["workflows"].extend(data.get("workflows", []))
                    for agent_info in data.get("agents", []):
                        name = agent_info.get("name", "")
                        if name and name not in self._plugin_agents:
                            # Store as simple dict agent (legacy shape)
                            self._plugin_agents[name] = agent_info
            except Exception:
                pass

    @property
    def agents(self) -> dict[str, AbstractAgent]:
        """Return all registered agents (native + plugins).

        Returns:
            Dict mapping agent names to instances.
        """
        return {**self._agents, **self._plugin_agents}

    def register_agent(self, name: str, agent: AbstractAgent) -> None:
        """Register a custom agent.

        Args:
            name: Agent name for routing.
            agent: Agent instance implementing AbstractAgent.
        """
        self._agents[name] = agent
        logger.info("Registered agent: %s", name)

    def get_agent(self, name: str) -> AbstractAgent:
        """Get an agent by name.

        Args:
            name: Agent name.

        Returns:
            The agent instance.

        Raises:
            KeyError: If no agent with that name exists.
        """
        if name in self._agents:
            return self._agents[name]
        if name in self._plugin_agents:
            return self._plugin_agents[name]
        raise KeyError(f"Agent '{name}' not found")

    def select_agent(self, task: dict[str, Any]) -> tuple[str, float]:
        """Select the best agent for a task based on can_handle() confidence.

        Args:
            task: Task dictionary.

        Returns:
            Tuple of (agent_name, confidence_score).
        """
        best_agent = "implementation"  # default
        best_confidence = 0.0

        for name, agent in self.agents.items():
            confidence = agent.can_handle(task)
            if confidence > best_confidence:
                best_confidence = confidence
                best_agent = name

        return best_agent, best_confidence

    def execute_task(
        self,
        task: dict[str, Any],
        *,
        task_id: str | None = None,
        model: Any = None,
    ) -> dict[str, Any]:
        """Execute a task through the full workflow.

        Workflow:
        1. Estimate complexity via ModelRouter
        2. Guardian assesses risk and HITL needs
        3. If HITL needed → return approval request
        4. Planner decomposes complex tasks
        5. Implementation executes with selected model
        6. Curator updates docs/memory
        7. Learning records outcome

        Args:
            task: Task dictionary with 'description' and optionally 'task_type'.
            task_id: Optional task ID (generated if not provided).
            model: Optional chat model instance.

        Returns:
            Dict with execution result and metadata.
        """
        task_id = task_id or str(uuid.uuid4())

        # Step 1: Estimate complexity
        complexity = self.router.estimate_complexity(task)
        risk = self._guardian.assess_risk(task)

        # Build context
        context = TaskContext(
            task_id=task_id,
            description=task.get("description", ""),
            task_type=task.get("task_type", "generic"),
            complexity=complexity,
            risk_level=risk,
            metadata=task.get("metadata", {}),
        )

        # Step 2: Guardian decides HITL
        guardian_result = self._guardian.execute(task, context)

        if guardian_result.needs_human_review:
            return {
                "task_id": task_id,
                "status": "needs_human_review",
                "complexity": complexity.value,
                "risk_level": risk.value,
                "review_reasons": guardian_result.review_reasons,
                "task": task,
            }

        # Step 3: Planner decomposes (for complex tasks)
        plan: list[dict[str, Any]] = []
        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.CRITICAL):
            plan_result = self._planner.execute(task, context, model)
            if plan_result.success:
                plan = plan_result.output.get("subtasks", [])

        # Step 4: Select model
        model_config = self.router.select_model(complexity)

        # Step 5: Implementation executes
        impl_result = self._implementation.execute(task, context, model)

        # Step 6: Curator updates docs (if needed)
        if impl_result.success and "files_changed" in task.get("metadata", {}):
            self._curator.execute(task, context, model)

        # Step 7: Learning records outcome
        if self.enable_learning:
            context.metadata["success"] = impl_result.success
            context.metadata["model_used"] = impl_result.model_used
            self._learning.execute(task, context, model)

        return {
            "task_id": task_id,
            "status": "completed" if impl_result.success else "failed",
            "complexity": complexity.value,
            "risk_level": risk.value,
            "model_tier": model_config["tier"],
            "plan": plan,
            "result": impl_result.to_dict(),
        }

    def route_to_agent(
        self, agent_name: str, task: dict[str, Any] | None = None
    ) -> Any:
        """Route a task directly to a specific agent.

        Supports legacy call `route_to_agent(name) -> dict` and new call
        `route_to_agent(name, task) -> AgentResult`.

        Args:
            agent_name: Name of the agent.
            task: Task dictionary (new API). If None, returns legacy dict.

        Returns:
            AgentResult (new API) or dict (legacy API).
        """
        # Legacy: stored as plain dict from registry.json
        legacy = self._plugin_agents.get(agent_name)
        if isinstance(legacy, dict) and not hasattr(legacy, "can_handle"):
            if task is None:
                return legacy
            # If legacy dict but task provided, return legacy dict anyway
            return legacy

        agent = self.get_agent(agent_name)
        if task is None:
            # Legacy compat: return agent info dict
            if isinstance(agent, dict):
                return agent
            return agent.get_info()
        # New API: need task
        complexity = self.router.estimate_complexity(task)
        risk = self._guardian.assess_risk(task)
        context = TaskContext(
            task_id=str(uuid.uuid4()),
            description=task.get("description", ""),
            task_type=task.get("task_type", "generic"),
            complexity=complexity,
            risk_level=risk,
            metadata=task.get("metadata", {}),
        )
        return agent.execute(task, context)

    def execute_workflow(
        self, workflow_name: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a named workflow.

        Framework-agnostic execution hook. Concrete frameworks provide
        their own executors and call into this orchestrator.

        Args:
            workflow_name: Name of the workflow to execute.
            context: Workflow context dictionary.

        Returns:
            Workflow execution result.
        """
        return {
            "workflow": workflow_name,
            "context": context,
            "status": "dispatched",
        }

    def get_agent_info(self) -> list[dict[str, Any]]:
        """Return info for all registered agents.

        Returns:
            List of agent info dicts.
        """
        return [
            {"name": name, **agent.get_info()}
            for name, agent in self.agents.items()
        ]

    def get_learning_stats(self) -> dict[str, Any]:
        """Return learning/outcome statistics.

        Returns:
            Dict with outcome stats from the ModelRouter.
        """
        return self.router.get_outcome_stats()
