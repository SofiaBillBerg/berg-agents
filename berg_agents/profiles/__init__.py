"""DeepAgents profile routing.

This package reads project settings and registers DeepAgents harness profiles
so agent behavior can be tuned per model without manual wiring.
"""

from __future__ import annotations

from berg_agents.profiles.router import (
    DEFAULT_PROFILES_CONFIG,
    load_profiles_from_config_file,
    register_profiles_from_config_file,
    register_profiles_from_settings,
)

__all__ = [
    "DEFAULT_PROFILES_CONFIG",
    "load_profiles_from_config_file",
    "register_profiles_from_config_file",
    "register_profiles_from_settings",
]
