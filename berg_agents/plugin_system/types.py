"""
Shared type definitions for the plugin system.

This file contains all types that are shared between modules to avoid
circular import issues.
"""

#  Berg Agents Plugin System - Shared Types

from dataclasses import dataclass
from typing import Any


@dataclass
class PluginDependency:
    """Plugin dependency specification."""

    id: str  # Plugin ID
    version: str  # Version constraint
    optional: bool = False  # Can be missing
    peer: bool = False  # Must exist, not managed


@dataclass
class ToolCapability:
    """Tool capability provided by a plugin."""

    type: str = "tool"
    id: str = ""
    name: str = ""
    description: str = ""
    tool: Any = None  # The actual tool function


# Simple PluginContext for basic testing
@dataclass
class SimplePluginContext:
    """Simple plugin context for testing."""

    plugin_id: str = ""
    plugin_version: str = ""
    plugin_dir: Any = None
    settings: dict[str, Any] | None = None


# Base plugin interface class
class BergPlugin:
    """Base interface for all berg_agents plugins."""

    async def on_load(self, context) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context) -> None:
        """Called when plugin is unloaded."""

    def get_capabilities(self) -> list[Any]:
        """Return plugin capabilities (tools, agents, etc.)."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return JSON schema for plugin settings."""
        return None
