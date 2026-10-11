"""Plugin metadata for the plugin system."""
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

# Plugin Metadata


from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataclasses import field
from feat_dev.plugin_dev.plugin_system.dependency.dependency_management import (
    PluginDependency,
)

# Plugin source type (literal string)
PluginSource = str  # One of: 'builtin', 'package', 'local', 'remote'


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

    # Behavior
    deferred: bool = True  # Enable deferred loading
    auto_enable: bool = False  # Enable on load

    # Runtime state
    enabled: bool = False
    loaded: bool = False
    error: Exception | None = None
