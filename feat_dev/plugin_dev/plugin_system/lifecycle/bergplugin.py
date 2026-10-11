"""Base class for all berg_agents plugins."""
#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

# 4. Plugin Interface Contract

# All plugins implement a base interface:

from abc import ABC, abstractmethod
import logging
from typing import Any

from feat_dev.plugin_dev.plugin_system.plugin_contract import (
    PluginCapability,
    PluginContext,
)

logger = logging.getLogger(__name__)


class BergPlugin(ABC):
    """Base interface for all berg_agents plugins."""

    @abstractmethod
    async def on_load(self, context: PluginContext) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context: PluginContext) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context: PluginContext) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context: PluginContext) -> None:
        """Called when plugin is unloaded."""

    def get_capabilities(self) -> list[PluginCapability]:
        """Return plugin capabilities (tools, agents, etc.)."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return JSON schema for plugin settings."""
        return None

    """Called when configuration changes.
    
    Optional hook - implement to support live reconfiguration.
    """

    async def on_config_change(
            self, context: PluginContext, new_config: dict[str, Any]
    ) -> None:
        """Called when configuration changes.

        Optional hook - implement to support live reconfiguration.
        """
