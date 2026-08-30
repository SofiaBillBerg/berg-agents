"""BergAgents — main application class.

This is the primary entry point for the BergAgents system. It wires together:
- Orchestrator (core engine)
- ModelRouter (complexity → model selection)
- OrchestratorServer (HTTP API)
- FastAPI web server
- CLI (Rich terminal UI)

Usage:
    # As a library
    app = BergAgentsApp.create()
    app.serve()  # Start web server

    # CLI
    # $ berg-agents serve
    # $ berg-agents orchestrate "refactor auth module"
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.model_router import ModelRouter
from berg_agents.core.orchestrator import Orchestrator
from berg_agents.ui.orchestrator_server import OrchestratorServer

logger = logging.getLogger(__name__)


class BergAgentsApp:
    """Main BergAgents application.

    Wires together the orchestrator, model router, and web server.
    Provides both programmatic and CLI interfaces.
    """

    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        orchestrator: Orchestrator | None = None,
        enable_learning: bool = True,
    ) -> None:
        """Initialize the BergAgents app.

        Args:
            router: Optional custom ModelRouter instance.
            orchestrator: Optional custom Orchestrator instance.
            enable_learning: Whether to enable the learning gate.
        """
        self.router = router or ModelRouter()
        self.orchestrator = orchestrator or Orchestrator(
            router=self.router,
            enable_learning=enable_learning,
        )
        self.server = OrchestratorServer()
        # Share the orchestrator with the server
        self.server.orchestrator = self.orchestrator

    @classmethod
    def create(cls, config: dict[str, Any] | None = None) -> BergAgentsApp:
        """Factory: create and configure the app.

        Args:
            config: Optional configuration dict. Keys:
                - enable_learning: bool (default True)
                - complexity_rules: dict for ModelRouter
                - tier_config: dict for ModelRouter
                - plugins: list of plugin paths (from bergagents.jsonc)

        Returns:
            Configured BergAgentsApp instance.
        """
        from pathlib import Path

        enable_learning = True
        router_kwargs: dict[str, Any] = {}
        plugins: list[Any] = []
        hitl_rules: dict[str, Any] | None = None
        agent_overrides: dict[str, Any] | None = None

        # 1) Explicit config dict (highest priority)
        if config:
            orch_cfg = config.get("orchestrator", {}) or {}
            enable_learning = orch_cfg.get("enable_learning", enable_learning)
            # model_routing may be at top-level or nested
            mr = config.get("model_routing") or {}
            if mr.get("tiers"):
                router_kwargs["tier_config"] = mr["tiers"]
            if mr.get("complexity_rules"):
                router_kwargs["complexity_rules"] = mr["complexity_rules"]
            # also support flat keys for backwards compat
            if "complexity_rules" in config:
                router_kwargs["complexity_rules"] = config["complexity_rules"]
            if "tier_config" in config:
                router_kwargs["tier_config"] = config["tier_config"]
            if "hitl_rules" in config:
                hitl_rules = config["hitl_rules"]
            if "agents" in config:
                agent_overrides = config["agents"]
            if "plugins" in config:
                for p in config["plugins"]:
                    plugins.append(Path(p))

        # 2) Global config (bergagents.jsonc via settings) if not already set
        try:
            from berg_agents.config.settings import get_settings

            settings = get_settings()
            s_dict = settings.model_dump()
            # orchestrator
            s_orch = s_dict.get("orchestrator") or {}
            if not config or "orchestrator" not in (config or {}):
                enable_learning = s_orch.get("enable_learning", enable_learning)
            # model_routing
            s_mr = s_dict.get("model_routing") or {}
            if not router_kwargs.get("tier_config") and s_mr.get("tiers"):
                router_kwargs["tier_config"] = s_mr["tiers"]
            if not router_kwargs.get("complexity_rules") and s_mr.get(
                "complexity_rules"
            ):
                router_kwargs["complexity_rules"] = s_mr["complexity_rules"]
            # hitl
            if hitl_rules is None:
                hitl_rules = s_dict.get("hitl_rules")
            # agents
            if agent_overrides is None:
                agent_overrides = s_dict.get("agents")
            # plugins
            if not plugins:
                cfg_plugins = s_dict.get("plugins") or []
                for p in cfg_plugins:
                    plugins.append(Path(p))
        except Exception:
            pass

        router = (
            ModelRouter(**router_kwargs) if router_kwargs else ModelRouter()
        )
        orchestrator = Orchestrator(
            plugins=plugins,
            router=router,
            enable_learning=enable_learning,
        )
        # Apply hitl/agent overrides if present
        if hitl_rules and hasattr(orchestrator, "_guardian"):
            g = orchestrator._guardian
            g.auto_execute = hitl_rules.get("auto_execute", g.auto_execute)
            g.notify_after = hitl_rules.get("notify_after", g.notify_after)
            g.ask_before = hitl_rules.get("ask_before", g.ask_before)
            g.human_leads = hitl_rules.get("human_leads", g.human_leads)
        if agent_overrides:
            for name, ov in agent_overrides.items():
                try:
                    agent = orchestrator.get_agent(name)
                    if "preferred_model_tier" in ov:
                        agent.preferred_model_tier = ov["preferred_model_tier"]
                except KeyError:
                    pass

        return cls(
            router=orchestrator.router,
            orchestrator=orchestrator,
            enable_learning=enable_learning,
        )

    def serve(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        """Start the FastAPI web server.

        Args:
            host: Host to bind to.
            port: Port to listen on.
        """
        from berg_agents.ui.web import app as fastapi_app
        import uvicorn

        logger.info("Starting BergAgents server on %s:%d", host, port)
        uvicorn.run(fastapi_app, host=host, port=port)

    def execute(
        self, description: str, task_type: str = "generic"
    ) -> dict[str, Any]:
        """Execute a task through the orchestrator.

        Args:
            description: Task description.
            task_type: Type of task.

        Returns:
            Execution result dict.
        """
        task = {"description": description, "task_type": task_type}
        return self.orchestrator.execute_task(task)

    def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agents.

        Returns:
            List of agent info dicts.
        """
        return self.orchestrator.get_agent_info()

    def get_learning_stats(self) -> dict[str, Any]:
        """Get learning/outcome statistics.

        Returns:
            Dict with outcome stats.
        """
        return self.orchestrator.get_learning_stats()

    def register_agent(self, name: str, agent: Any) -> None:
        """Register a custom agent.

        Args:
            name: Agent name.
            agent: Agent instance implementing AbstractAgent.
        """
        self.orchestrator.register_agent(name, agent)


# ---------------------------------------------------------------------------
# Singleton for CLI/server use
# ---------------------------------------------------------------------------

_app: BergAgentsApp | None = None


def get_app() -> BergAgentsApp:
    """Return the singleton BergAgentsApp instance."""
    global _app
    if _app is None:
        _app = BergAgentsApp.create()
    return _app
