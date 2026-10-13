# Performance Optimizations

import asyncio
import importlib
import json
from pathlib import Path

from attrs import asdict

from berg_agents.plugin_system.discovery.discovery_process import (
    discover_local_plugins,
    discover_package_plugins,
)
# Lazy Import
from berg_agents.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
)
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin


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
    return discover_local_plugins(plugin_dir=Path("./.berg_config/plugins"))


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
