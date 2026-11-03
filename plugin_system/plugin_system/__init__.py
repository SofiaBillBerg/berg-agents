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

"""Berg Agents plugin system public surface."""

# NOTE: Explicit re-exports (no `from package import *` self-import).
# NOTE: The host (berg_agents) imports these by name from the package
# root — the agent seam (`get_plugin_tools_for` for any role),
# `ensure_plugin_system_ready` for warming, plus `list_chat_plugins` /
# `set_plugin_enabled` / `get_chat_plugin_state` and `plugin_slug`.
# They are re-exported here so there is ONE import path
# (`from plugin_system import ...`) instead of callers reaching into
# individual submodules — two ways to fetch the same symbol is a
# near-duplicate variant.
from plugin_system.chat_integration import (
    ensure_plugin_system_ready,
    get_chat_plugin_state,
    get_plugin_manager,
    get_plugin_tools_for,
    list_chat_plugins,
    set_plugin_enabled,
)
from plugin_system.config.config_manager import plugin_slug
from plugin_system.lifecycle.bergplugin import BergPlugin
from plugin_system.plugin_context import PluginContext
from plugin_system.plugin_contract import (
    AgentCapability,
    BackendCapability,
    MCPCapability,
    PluginCapability,
    ProviderCapability,
    SkillCapability,
    ToolCapability,
)
from plugin_system.plugin_manager import PluginManager

__all__ = [
    "AgentCapability",
    "BackendCapability",
    "BergPlugin",
    "MCPCapability",
    "PluginCapability",
    "PluginContext",
    "PluginManager",
    "ProviderCapability",
    "SkillCapability",
    "ToolCapability",
    "ensure_plugin_system_ready",
    "get_chat_plugin_state",
    "get_plugin_manager",
    "get_plugin_tools_for",
    "list_chat_plugins",
    "plugin_slug",
    "set_plugin_enabled"]
