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

"""Module for plugin metadata."""
# Plugin Metadata

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from berg_agents.plugin_system.dependency.plugin_dependency import (
    PluginDependency,
)
from berg_agents.plugin_system.discovery.plugin_sources import PluginSource


@dataclass
class PluginMetadata:
    """Plugin discovery metadata."""

    # Identity
    id: str  # Unique identifier
    version: str  # Semantic version
    name: str  # Human-readable name
    description: str  # Brief description

    # Location
    source: PluginSource  # "builtin", "package", "local", "remote"
    path: Path | None  # Filesystem path (if applicable)
    entry_point: str  # Python import path

    # Metadata
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    repository: str | None = None
    tags: list[str] = field(default_factory=list)
    icon: str | None = None

    # Requirements
    dependencies: list[PluginDependency] = field(default_factory=list)
    python_requires: str | None = None
    berg_agents_requires: str | None = None

    # Configuration
    settings_schema: dict[str, Any] | None = None
    permissions: list[str] = field(default_factory=list)

    # UI surface (optional): declared by the plugin's manifest, so a
    # plugin ships its own component and the host only renders it.
    ui: dict[str, Any] | None = None

    # Behavior
    deferred: bool = True  # Enable deferred loading
    auto_enable: bool = False  # Enable on load

    # Runtime state
    enabled: bool = False
    loaded: bool = False
    error: Exception | None = None
