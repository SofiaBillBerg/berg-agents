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

"""Backward-compatibility adapters: old formats as plugins.

Phase 1 of the migration guide (``berg_plugins/plugin_dev/12-migration-guide.md``):
existing capabilities keep working by wrapping them as plugins, so no
skill or server has to be rewritten to join the plugin system.
"""

from plugin_system.adapters.mcp_adapter import (
    MCPPluginAdapter,
    build_mcp_metadata,
    describe_mcp_server,
    register_mcp_plugins,
)
from plugin_system.adapters.skill_adapter import (
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
