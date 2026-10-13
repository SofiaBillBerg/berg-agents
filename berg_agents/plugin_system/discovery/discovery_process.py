# Discovery Algorithm


import asyncio
import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml

from berg_agents.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
)

logger = logging.getLogger(__name__)


# **Discovery mechanism:**


def extract_metadata(plugin_class) -> PluginMetadata:
    """Extract metadata from plugin class."""
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


def discover_package_plugins() -> list[PluginMetadata]:
    """Discover plugins from installed packages."""
    discovered = []
    for ep in entry_points(group="berg_plugins"):
        try:
            plugin_class = ep.load()
            metadata = extract_metadata(plugin_class)
            discovered.append(metadata)
        except Exception as e:
            logger.warning(f"Failed to load plugin {ep.name}: {e}")
    return discovered


# **Discovery:**


def parse_manifest(manifest_path: Path) -> PluginMetadata:
    """Parse plugin manifest file."""
    with Path(manifest_path).open() as f:
        manifest = yaml.safe_load(f)
    return PluginMetadata(
        id=manifest.get("id"),
        version=manifest.get("version", "0.0.1"),
        name=manifest.get("name"),
        description=manifest.get("description", ""),
        source="local",
        path=manifest_path,
        entry_point=manifest.get("entry_point"),
        permissions=manifest.get("permissions"),
        dependencies=manifest.get("dependencies"),
        tags=manifest.get("tags"),
    )


def discover_local_plugins(plugin_dir: Path) -> list[PluginMetadata]:
    """Discover plugins from local directory."""
    discovered = []
    for item in plugin_dir.iterdir():
        if not item.is_dir():
            continue
        manifest_path = item / "plugin.yaml"
        if manifest_path.exists():
            try:
                metadata = parse_manifest(manifest_path)
                discovered.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to parse {manifest_path}: {e}")
    return discovered


class PluginDiscovery:
    """Plugin discovery coordinator."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.plugin_dir = Path(config.get("plugin_dir", ".berg_config/plugins"))
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
                logger.error(f"Discovery failed: {result}")
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
                metadata = self._extract_metadata(plugin_class, ep.name)
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
                    metadata = await self._parse_manifest(manifest_path)
                    discovered.append(metadata)
                except Exception as e:
                    logger.warning(f"Failed to parse {manifest_path}: {e}")
        return discovered

    async def _parse_manifest(self, manifest_path: Path) -> PluginMetadata:
        """Parse plugin manifest YAML file.

        Args:
            manifest_path: Path to plugin.yaml file

        Returns:
            Plugin metadata
        """
        with Path(manifest_path).open() as f:
            data = yaml.safe_load(f)

        # Parse dependencies
        from berg_agents.plugin_system.dependency.plugin_dependency import (
            PluginDependency,
        )

        dependencies = []
        for dep_data in data.get("dependencies", []):
            dep = PluginDependency(
                id=dep_data["id"],
                version=dep_data["version"],
                optional=dep_data.get("optional", False),
            )
            dependencies.append(dep)

        # Get author info
        author_data = data.get("author", {})
        author = (
            author_data.get("name")
            if isinstance(author_data, dict)
            else author_data
        )

        return PluginMetadata(
            id=data["id"],
            version=data["version"],
            name=data["name"],
            description=data["description"],
            source="local",
            path=manifest_path.parent,
            entry_point=data["entry_point"],
            author=author,
            license=data.get("license"),
            homepage=data.get("homepage"),
            repository=data.get("repository"),
            tags=data.get("tags", []),
            icon=data.get("icon"),
            dependencies=dependencies,
            permissions=data.get("permissions", []),
        )

    def _extract_metadata(self, plugin_class, name: str) -> PluginMetadata:
        """Extract metadata from plugin class."""
        return PluginMetadata(
            id=getattr(plugin_class, "plugin_id", name),
            version=getattr(plugin_class, "plugin_version", "0.0.1"),
            name=getattr(plugin_class, "plugin_name", name),
            description=getattr(plugin_class, "plugin_description", ""),
            source="package",
            path=None,
            entry_point=f"{plugin_class.__module__}.{plugin_class.__name__}",
            permissions=getattr(plugin_class, "plugin_permissions", []),
            dependencies=getattr(plugin_class, "plugin_dependencies", []),
            tags=getattr(plugin_class, "plugin_tags", []),
        )
