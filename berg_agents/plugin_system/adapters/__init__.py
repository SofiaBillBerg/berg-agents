"""Backward-compatibility adapters: old formats as plugins.

Phase 1 of the migration guide (``berg_plugins/plugin_dev/12-migration-guide.md``):
existing capabilities keep working by wrapping them as plugins, so no
skill or server has to be rewritten to join the plugin system.
"""

from berg_agents.plugin_system.adapters.mcp_adapter import (
    MCPPluginAdapter,
    build_mcp_metadata,
    describe_mcp_server,
    register_mcp_plugins,
)
from berg_agents.plugin_system.adapters.skill_adapter import (
    SkillPluginAdapter,
    build_skill_metadata,
    register_skill_plugins,
)

__all__ = [
    "MCPPluginAdapter",
    "SkillPluginAdapter",
    "build_mcp_metadata",
    "build_skill_metadata",
    "describe_mcp_server",
    "register_mcp_plugins",
    "register_skill_plugins"]
