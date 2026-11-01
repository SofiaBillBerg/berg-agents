# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

    async def on_load(self, context: SimplePluginContext) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context: SimplePluginContext) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context: SimplePluginContext) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context: SimplePluginContext) -> None:
        """Called when plugin is unloaded."""

    def get_capabilities(self) -> list[Any]:  # ruff: ignore[no-self-use]
        """Return plugin capabilities (tools, agents, etc.)."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:  # ruff: ignore[no-self-use]
        """Return JSON schema for plugin settings."""
        return None
