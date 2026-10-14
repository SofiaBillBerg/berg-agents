from pathlib import Path
from typing import Any

from berg_agents.plugin_system.discovery.compat_funcs import (
    create_mcp_toolset,
    parse_skill,
)

# Backward Compatibility
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.plugin_context import PluginContext
from berg_agents.plugin_system.plugin_contract import (  # PluginContext,
    PluginCapability,
    ToolCapability,
)

# Skill Adapter

# Wrap existing skills as plugins:


class CapabilityWrapper(PluginCapability):
    """Wrap skill content as a plugin capability PluginCapability."""

    def __init__(
        self,
        type: str,
        id: str,
        description: str,
        content: str,
        deferred: bool = True,
    ) -> None:
        self.type = type
        self.id = id
        self.description = description
        self.content = content
        self.deferred = deferred


class SkillPluginAdapter(BergPlugin):
    """Adapter to wrap existing skills as plugins."""

    def __init__(self, skill_path: Path) -> None:
        self.skill_path = skill_path
        self.skill_data = None

    async def on_load(self, context: PluginContext) -> None:
        """Load skill content."""
        self.skill_data = parse_skill(self.skill_path)

    def get_capabilities(self) -> list[PluginCapability]:
        """Return skill as a capability."""
        return [
            CapabilityWrapper(
                type="skill",
                id=self.skill_data["name"],
                description=self.skill_data["description"],
                content=self.skill_data["body"],
                deferred=True,
            )
        ]


# MCP Adapter

# Wrap MCP servers as plugins:


class MCPPluginAdapter(BergPlugin):
    """Adapter to wrap MCP servers as plugins."""

    def __init__(self, server_config: dict[str, Any]) -> None:
        """Initialize the MCP plugin adapter.

        :param server_config: Configuration for the MCP server
        """
        self.config = server_config
        self.toolset = None

    async def on_load(self, context: PluginContext) -> None:
        """Initialize MCP connection."""
        self.toolset = await create_mcp_toolset(self.config)

    def get_capabilities(self) -> list[PluginCapability]:
        """Return MCP tools as capabilities."""
        return [
            ToolCapability(tool=tool, risk_level="medium", deferred=False)
            for tool in self.toolset.tools
        ]
