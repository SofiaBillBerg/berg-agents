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
"""Performance Optimizations."""

import asyncio
import importlib
import json
from pathlib import Path

from plugin_system.discovery.discovery_process import (
    discover_local_plugins,
    discover_package_plugins,
)

# Lazy Import
from plugin_system.discovery.plugin_metadata import PluginMetadata
from plugin_system.lifecycle.bergplugin import BergPlugin

from attrs import asdict


def lazy_import_plugin(entry_point: str) -> type[BergPlugin]:
    """Import plugin class only when needed."""
    module_path, class_name = entry_point.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


# Parallel Discovery


def discover_builtin():
    """Discover built-in plugins."""
    # Placeholder for built-in plugin discovery logic
    return discover_builtin()


def discover_packages() -> list[PluginMetadata]:
    """Discover plugins from installed packages."""
    return discover_package_plugins()


def discover_local() -> list[PluginMetadata]:
    """Discover local plugins."""
    return discover_local_plugins(plugin_dir=Path("./.berg-agents/plugins"))


async def discover_all_parallel() -> list[PluginMetadata]:
    """Discover plugins in parallel."""
    tasks = [discover_builtin(), discover_packages(), discover_local()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        p
        for result in results
        if not isinstance(result, Exception)
        for p in result
    ]


# Caching


class PluginCache:
    """Cache for plugin metadata."""

    def __init__(self, cache_file: Path) -> None:
        """Initialize cache with a file path."""
        self.cache_file = cache_file
        self.cache: dict[str, PluginMetadata] = {}

    def load(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            data = json.loads(self.cache_file.read_text())
            self.cache = {k: PluginMetadata(**v) for k, v in data.items()}

    def save(self) -> None:
        """Save cache to disk."""
        data = {k: asdict(v) for k, v in self.cache.items()}
        self.cache_file.write_text(json.dumps(data, indent=2))

    def get(self, plugin_id: str, version: str) -> PluginMetadata | None:
        """Get cached metadata."""
        key = f"{plugin_id}@{version}"
        return self.cache.get(key)

    def set(self, metadata: PluginMetadata) -> None:
        """Cache metadata."""
        key = f"{metadata.id}@{metadata.version}"
        self.cache[key] = metadata
