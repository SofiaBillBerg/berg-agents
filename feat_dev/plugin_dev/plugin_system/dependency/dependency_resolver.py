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

from collections import defaultdict
from dataclasses import dataclass, field

from feat_dev.plugin_dev.plugin_system.dependency.dependency_management import DependencyVersionError, \
    DependencyNotEnabledError, DependencyNotFoundError, DependencyGraph, DependencyResolver, VersionConflictError
from feat_dev.plugin_dev.plugin_system.dependency.version_parsing import Version, VersionConstraint
from feat_dev.plugin_dev.plugin_system.discovery.plugin_metadata import PluginMetadata
from feat_dev.plugin_dev.plugin_system.discovery.plugin_registry import PluginRegistry
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_hooks import PluginNotFoundError
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_states import PluginState
import logging

logger=logging.getLogger(__name__)

# Conflict Resolution

# Version Conflicts


class ConflictResolver:
    """Resolve version conflicts."""

    def resolve_conflicts(
            self, plugins: list[PluginMetadata]
    ) -> list[PluginMetadata]:
        """Resolve version conflicts.

        When multiple plugins require different versions of the same
        dependency, choose the highest version that satisfies all constraints.

        Args:
            plugins: List of plugin metadata

        Returns:
            Resolved plugin list

        Raises:
            VersionConflictError: If no compatible version exists
        """
        # Group plugins by ID
        by_id: dict[str, list[PluginMetadata]] = field(default_factory=lambda: defaultdict(list))
        for plugin in plugins:
            by_id[plugin.id].append(plugin)

        resolved = []

        for plugin_id, versions in by_id.items():
            if len(versions) == 1:
                resolved.append(versions[0])
                continue

            # Multiple versions - find highest compatible
            candidates = sorted(
                versions, key=lambda p: Version.parse(p.version), reverse=True
            )

            # Collect all constraints for this plugin
            constraints = []
            for plugin in plugins:
                for dep in plugin.dependencies:
                    if dep.id == plugin_id:
                        constraints.append(dep.version)

            # Find version that satisfies all constraints
            for candidate in candidates:
                version = Version.parse(candidate.version)
                if all(
                        VersionConstraint.parse(c).matches(version)
                        for c in constraints
                ):
                    resolved.append(candidate)
                    break
            else:
                raise VersionConflictError(
                    f"No compatible version found for {plugin_id}. "
                    f"Constraints: {', '.join(constraints)}"
                )

        return resolved


# Load Order Calculation


class LoadOrderCalculator:
    """Calculate plugin load order."""

    def __init__(self, resolver: DependencyResolver) -> None:
        self.resolver = resolver

    async def calculate(
            self,
            plugins: list[PluginMetadata],
            priority_hints: dict[str, int] | None = None,
    ) -> list[str]:
        """Calculate load order with optional priority hints.

        Args:
            plugins: List of plugin metadata
            priority_hints: Optional priority values (higher = earlier)

        Returns:
            List of plugin IDs in load order
        """
        # Resolve dependencies
        load_order, warnings = await self.resolver.resolve(plugins)

        # Log warnings
        for warning in warnings:
            logger.warning(warning)

        # Apply priority hints if provided
        if priority_hints:
            load_order = self._apply_priorities(load_order, priority_hints)

        return load_order

    def _apply_priorities(
            self, load_order: list[str], priorities: dict[str, int]
    ) -> list[str]:
        """Apply priority hints while respecting dependencies.

        Higher priority plugins load earlier, but dependencies
        must still load before dependents.
        """
        # Build dependency constraints
        graph = DependencyGraph()
        for plugin_id in load_order:
            # Would need access to metadata here
            pass

        # Sort by priority within dependency constraints
        # This is a topological sort with priority as secondary key
        # (Implementation would go here)

        return load_order


# Runtime Dependency Checking


class RuntimeDependencyChecker:
    """Check dependencies at runtime."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry

    async def check_before_enable(self, plugin_id: str) -> None:
        """Check dependencies before enabling plugin.

        Raises:
            DependencyError: If dependencies not satisfied
        """
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        # Check required dependencies are enabled
        for dep in entry.metadata.dependencies:
            if dep.optional or dep.peer:
                continue

            dep_entry = self.registry.get(dep.id)
            if not dep_entry:
                raise DependencyNotFoundError(
                    f"Required dependency not found: {dep.id}"
                )

            if dep_entry.state != PluginState.ENABLED:
                raise DependencyNotEnabledError(
                    f"Required dependency not enabled: {dep.id}"
                )

            # Check version
            if not dep.is_satisfied_by(dep_entry.metadata.version):
                raise DependencyVersionError(
                    f"Version mismatch: requires {dep.id} {dep.version}, "
                    f"found {dep_entry.metadata.version}"
                )

    async def check_before_disable(self, plugin_id: str) -> list[str]:
        """Check dependents before disabling plugin.

        Returns:
            List of dependent plugin IDs that would break
        """
        entry = self.registry.get(plugin_id)
        if not entry:
            return []

        # Find enabled plugins that depend on this one
        dependents = []
        for other in self.registry.list_plugins(state=PluginState.ENABLED):
            for dep in other.metadata.dependencies:
                if dep.id == plugin_id and not dep.optional:
                    dependents.append(other.metadata.id)
                    break

        return dependents


# Plugin API Versioning


@dataclass
class PluginAPIVersion:
    """Plugin API version."""

    version: str

    # What changed
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


# Plugin API version history
PLUGIN_API_VERSIONS = [
    PluginAPIVersion(
        version="1.0.0",
        added=["BergPlugin", "PluginContext", "PluginCapability"],
        changed=["BergPlugin", "PluginContext", "PluginCapability"],
        deprecated=["BergPlugin", "PluginContext", "PluginCapability"],
        removed=["BergPlugin", "PluginContext", "PluginCapability"],
    ),
    PluginAPIVersion(
        version="1.1.0",
        added=["health_check", "EventBus"],
        deprecated=["legacy_hook"],
        changed=["BergPlugin", "PluginContext", "PluginCapability"],
        removed=["BergPlugin", "PluginContext", "PluginCapability"],

    )]


def check_api_compatibility(
        plugin_api_version: str, current_version: str
) -> bool:
    """Check if plugin API version is compatible."""
    plugin_ver = Version.parse(plugin_api_version)
    current_ver = Version.parse(current_version)

    # Same major version = compatible
    return plugin_ver.major == current_ver.major
