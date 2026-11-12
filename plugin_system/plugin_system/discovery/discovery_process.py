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
"""Plugin discovery process."""

# Discovery Algorithm

import asyncio
import logging

from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml

from plugin_system.discovery.plugin_metadata import PluginMetadata


logger = logging.getLogger(__name__)


# **Discovery mechanism:**


def extract_metadata(plugin_class: Any) -> PluginMetadata:
    """Extract metadata from a plugin class (the package install path).

    :param plugin_class: A :class:`BergPlugin` subclass exported through
        the ``berg_plugins`` entry point.
    :return: Metadata describing that plugin.
    """
    return PluginMetadata(
        id=getattr(plugin_class, "plugin_id", None),
        version=getattr(plugin_class, "plugin_version", "0.0.1"),
        name=getattr(plugin_class, "plugin_name", None),
        description=getattr(plugin_class, "plugin_description", ""),
        source="package",
        path=None,
        entry_point=f"{plugin_class.__module__}.{plugin_class.__name__}",
        permissions=getattr(plugin_class, "plugin_permissions", []),
        dependencies=getattr(plugin_class, "plugin_dependencies", []),
        tags=getattr(plugin_class, "plugin_tags", []),
    )


# **Discovery:**


def load_manifest(manifest_path: Path) -> PluginMetadata:
    """Parse and validate one ``plugin.yaml`` into discovery metadata.

    The manifest is validated by :class:`PluginManifest` (the single
    schema) and converted by ``to_metadata`` — one place where a file
    field becomes a runtime field, so nothing can be validated and then
    dropped on the way.

    :param manifest_path: Path to the plugin's ``plugin.yaml``.
    :return: Populated ``PluginMetadata``.
    :raises Exception: On unreadable YAML or an invalid manifest; callers
        log and skip the plugin.
    """
    from plugin_system.plugin_schema import PluginManifest

    with Path(manifest_path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    manifest = PluginManifest(**raw)
    # The record keeps the plugin's *folder*: plugin code and its UI
    # bundle resolve relative to it, not to the manifest file.
    return manifest.to_metadata(path=Path(manifest_path).parent)


class PluginDiscovery:
    """Plugin discovery coordinator."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.plugin_dir = Path(config.get("plugin_dir", ".berg-agents/plugins"))
        self.cache_dir = Path(config.get("cache_dir", ".cache/plugins"))

    async def discover_all(
        self, search_paths: list[Path] | None = None
    ) -> list[PluginMetadata]:
        """Discover plugins from all sources.

        Args:
            search_paths: Optional list of paths to search. If provided, only searches these paths.
                         If None, searches built-in, packages, and default local directory.

        Returns:
            List of discovered plugin metadata
        """
        if search_paths:
            # Search only the specified paths
            results = await asyncio.gather(
                *[self._scan_directory(path) for path in search_paths],
                return_exceptions=True,
            )
        else:
            # Search all default sources
            results = await asyncio.gather(
                self._discover_builtin(),
                self._discover_packages(),
                self._discover_local(),
                return_exceptions=True,
            )

        # Flatten and filter errors
        discovered = []
        for result in results:
            if isinstance(result, Exception):
                logger.exception(f"Discovery failed: {result}")
            else:
                discovered.extend(result)

        # Deduplicate by plugin_id (priority order)
        seen = {}
        for plugin in discovered:
            if plugin.id not in seen:
                seen[plugin.id] = plugin
            else:
                logger.debug(f"Skipping duplicate plugin: {plugin.id}")

        return list(seen.values())

    async def _discover_builtin(self) -> list[PluginMetadata]:
        """Discover built-in plugins."""
        builtin_dir = Path(__file__).parent.parent / "plugins" / "builtin"
        if not builtin_dir.exists():
            return []
        return await self._scan_directory(builtin_dir)

    async def _discover_packages(self) -> list[PluginMetadata]:
        """Discover installed package plugins."""
        discovered = []
        for ep in entry_points(group="berg_plugins"):
            try:
                plugin_class = ep.load()
                metadata = extract_metadata(plugin_class)
                discovered.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load plugin {ep.name}: {e}")
        return discovered

    async def _discover_local(self) -> list[PluginMetadata]:
        """Discover local directory plugins."""
        if not self.plugin_dir.exists():
            return []
        return await self._scan_directory(self.plugin_dir)

    async def _scan_directory(self, directory: Path) -> list[PluginMetadata]:
        """Scan directory for plugin manifests."""
        discovered = []
        for item in directory.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "plugin.yaml"
            if manifest_path.exists():
                try:
                    metadata = load_manifest(manifest_path)
                    discovered.append(metadata)
                except Exception as e:
                    logger.warning(f"Failed to parse {manifest_path}: {e}")
        return discovered
