"""Berg Agents plugin system public surface."""

# NOTE: Explicit re-exports (no `from package import *` self-import).
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.plugin_context import PluginContext
from berg_agents.plugin_system.plugin_contract import (
    AgentCapability,
    BackendCapability,
    MCPCapability,
    PluginCapability,
    ProviderCapability,
    SkillCapability,
    ToolCapability,
)
from berg_agents.plugin_system.plugin_manager import PluginManager

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
    "ToolCapability"]
