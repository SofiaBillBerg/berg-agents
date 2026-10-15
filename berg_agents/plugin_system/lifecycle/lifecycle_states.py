# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

from enum import StrEnum


class PluginState(StrEnum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"  # Found but not loaded
    LOADING = "loading"  # Import in progress
    LOADED = "loaded"  # Manifest parsed, code imported
    ENABLING = "enabling"  # Activation in progress
    ENABLED = "enabled"  # Active and available
    DISABLING = "disabling"  # Deactivation in progress
    DISABLED = "disabled"  # Present but inactive
    UNLOADING = "unloading"  # Cleanup in progress
    ERROR = "error"  # Failed to load or crashed
    DEPRECATED = "deprecated"  # Marked for removal
