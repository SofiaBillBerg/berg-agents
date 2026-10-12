"""BergAgents - main application class.

This is the primary entry point for the BergAgents system. It wires together:
- Harness (core engine: guardian → planner → implementation → curator)
- FastAPI web server (ui.server: routes + session state)
- CLI (Rich terminal UI)

Usage:
    # As a library
    app = BergAgentsApp.create()
    app.serve()  # Start web server

    # CLI
    # $ python -m berg_agents --web
    # $ python -m berg_agents --tui
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from berg_agents.agents.guardian import GuardianDeps
from berg_agents.core.harness import Harness

logger = logging.getLogger(__name__)


@dataclass
class _CreateOptions:
    """Mutable option bundle for BergAgentsApp.create()."""

    enable_learning: bool = True
    enable_inference: bool = True
    model_routing: dict[str, Any] | None = None
    hitl_rules: dict[str, Any] | None = None
    agent_overrides: dict[str, Any] | None = None


def _apply_explicit_config(
        opts: _CreateOptions, config: dict[str, Any]
) -> None:
    """Apply the explicit config dict (highest priority).

    Args:
        opts: Option bundle mutated in place.
        config: User-supplied configuration dict.
    """
    harness_cfg = config.get("harness", {}) or {}
    opts.enable_learning = harness_cfg.get(
        "enable_learning", opts.enable_learning
    )
    opts.enable_inference = harness_cfg.get(
        "enable_inference", opts.enable_inference
    )
    # model_routing passes through as-is (models by complexity).
    mr = config.get("model_routing") or {}
    if mr:
        opts.model_routing = dict(mr)
    if "hitl_rules" in config:
        opts.hitl_rules = config["hitl_rules"]
    if "agents" in config:
        opts.agent_overrides = config["agents"]


def _apply_global_settings(
        opts: _CreateOptions, config: dict[str, Any] | None
) -> None:
    """Merge bergagents.jsonc settings for options not set explicitly.

    Args:
        opts: Option bundle mutated in place.
        config: Explicit config dict (used to detect overrides).
    """
    try:
        from berg_agents.config.settings import get_settings

        settings = get_settings()
        s_dict = settings.model_dump()
        # harness
        s_harness = s_dict.get("harness") or {}
        if not config or "harness" not in (config or {}):
            opts.enable_learning = s_harness.get(
                "enable_learning", opts.enable_learning
            )
            opts.enable_inference = s_harness.get(
                "enable_inference", opts.enable_inference
            )
        # hitl
        if opts.hitl_rules is None:
            opts.hitl_rules = s_dict.get("hitl_rules")
        # agents
        if opts.agent_overrides is None:
            opts.agent_overrides = s_dict.get("agents")
    except Exception as exc:
        logger.debug("Global settings unavailable: %s", exc)


def _guardian_gate_kwargs(
        hitl_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build GuardianDeps kwargs from known HITL gate lists.

    Only known gate lists override the GuardianDeps defaults;
    anything else is ignored, not fatal.

    Args:
        hitl_rules: HITL gate list overrides.

    Returns:
        Kwargs for GuardianDeps.
    """
    gate_kwargs: dict[str, Any] = {}
    if hitl_rules:
        for key in (
                "auto_execute",
                "notify_after",
                "ask_before",
                "human_leads",
        ):
            value = hitl_rules.get(key)
            if isinstance(value, list):
                gate_kwargs[key] = list(value)
    return gate_kwargs


def _apply_agent_overrides(
        harness: Harness, agent_overrides: dict[str, Any] | None
) -> None:
    """Apply per-agent preferred-complexity overrides to a harness.

    Args:
        harness: Harness whose agents are updated in place.
        agent_overrides: Per-agent override mapping.
    """
    if agent_overrides:
        for name, ov in agent_overrides.items():
            try:
                agent = harness.get_agent(name)
                if "preferred_complexity" in ov:
                    agent.preferred_complexity = ov["preferred_complexity"]
            except KeyError:
                pass


class BergAgentsApp:
    """Main BergAgents application.

    Wires together the harness and the web server. Provides
    both programmatic and CLI interfaces.
    """

    def __init__(
            self,
            *,
            harness: Harness | None = None,
            enable_learning: bool = True,
            enable_inference: bool = True,
    ) -> None:
        """Initialize the BergAgents app.

        :param harness: Optional custom Harness instance.
        :param enable_learning: Whether to enable the learning gate.
        :param enable_inference: Whether the default harness may
            call the model synchronously.
        """
        self.harness = harness or Harness(
            enable_learning=enable_learning,
            enable_inference=enable_inference,
        )

    @classmethod
    def create(cls, config: dict[str, Any] | None = None) -> BergAgentsApp:
        """Factory: create and configure the app.

        :param cls: Class to instantiate (subclassing supported).
        :param config: Optional configuration dict. Keys:
                - enable_learning: bool (default True)
                - enable_inference: bool (default True)
                - model_routing: models by complexity
                - hitl_rules: HITL gate list overrides
                - agents: per-agent overrides
                  (preferred_complexity)

        :return: Configured BergAgentsApp instance.
        """
        opts = _CreateOptions()

        # 1) Explicit config dict (highest priority)
        if config:
            _apply_explicit_config(opts, config)

        # 2) Global config (bergagents.jsonc via settings) if not set
        _apply_global_settings(opts, config)

        harness = Harness(
            enable_learning=opts.enable_learning,
            enable_inference=opts.enable_inference,
            hitl_gates=GuardianDeps(**_guardian_gate_kwargs(opts.hitl_rules)),
            model_cfg=(
                {"model_routing": opts.model_routing}
                if opts.model_routing
                else None
            ),
        )
        # Apply agent overrides if present
        _apply_agent_overrides(harness, opts.agent_overrides)

        return cls(
            harness=harness,
            enable_learning=opts.enable_learning,
            enable_inference=opts.enable_inference,
        )

    def serve(self, host: str = "0.0.0.0", port: int = 8001) -> None:
        """Start the FastAPI web server.

        :param host: Host to bind to.
        :param port: Port to listen on.
        """
        from berg_agents.ui.server import create_app
        import uvicorn

        logger.info("Starting BergAgents server on %s:%d", host, port)
        uvicorn.run(create_app(self.harness), host=host, port=port)

    def execute(
            self, description: str, task_type: str = "generic"
    ) -> dict[str, Any]:
        """Execute a task through the harness.


        :param description: Task description.
        :param task_type: Type of task.

        :return: Execution result dict.
        """
        task = {"description": description, "task_type": task_type}
        return self.harness.execute_task(task)

    def get_learning_stats(self) -> dict[str, Any]:
        """Get learning/outcome statistics.

        :return: Dict with outcome stats.
        """
        return self.harness.get_learning_stats()

    def register_agent(self, name: str, agent: Any) -> None:
        """Register a custom agent.

        :param name: Agent name.
        :param agent: Agent instance implementing AbstractAgent.
        """
        self.harness.register_agent(name, agent)


# ---------------------------------------------------------------------------
# Singleton for CLI/server use
# ---------------------------------------------------------------------------

_app_holder: list[BergAgentsApp] = []


def get_app() -> BergAgentsApp:
    """Return the singleton BergAgentsApp instance.

    :return: BergAgentsApp instance.
    """
    if not _app_holder:
        _app_holder.append(BergAgentsApp.create())
    return _app_holder[0]
