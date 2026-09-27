"""BergAgents profile routing.

This package reads project settings and registers BergAgents harness profiles
so agent behavior can be tuned per model without manual wiring.
"""

from __future__ import annotations

from berg_agents.profiles.router import DEFAULT_PROFILES_CONFIG

__all__ = ["DEFAULT_PROFILES_CONFIG"]
