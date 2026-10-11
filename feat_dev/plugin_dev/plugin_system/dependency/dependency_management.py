"""Dependency management for the plugin system."""
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

from collections import defaultdict, deque
from dataclasses import dataclass
import logging

# Dependency Types
from feat_dev.plugin_dev.plugin_system.dependency.version_parsing import (
    Version,
    VersionConstraint,
)
from feat_dev.plugin_dev.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
)
from feat_dev.plugin_dev.plugin_system.exceptions import (
    DependencyCycleError,
    DependencyError,
    DependencyNotFoundError,
    DependencyVersionError,
)
from feat_dev.plugin_dev.plugin_system.discovery.plugin_registry import (
    PluginRegistry,
)

logger = logging.getLogger(__name__)


@dataclass
class PluginDependency:
    """Plugin dependency specification."""

    id: str  # Plugin ID
    version: str  # Version constraint
    optional: bool = False  # Can be missing
    peer: bool = False  # Must exist, not managed

    def is_satisfied_by(self, available_version: str) -> bool:
        """Check if available version satisfies constraint."""
        constraint = VersionConstraint.parse(self.version)
        version = Version.parse(available_version)
        return constraint.matches(version)


# Dependency Resolution Algorithm

# Dependency Graph


class DependencyGraph:
    """Plugin dependency graph."""

    def __init__(self) -> None:
        self.nodes: dict[str, PluginMetadata] = {}
        self.edges: dict[str, list[str]] = defaultdict(list)
        self.reverse_edges: dict[str, list[str]] = defaultdict(list)

    def add_plugin(self, metadata: PluginMetadata) -> None:
        """Add plugin to graph."""
        self.nodes[metadata.id] = metadata

        for dep in metadata.dependencies:
            if not dep.optional:
                self.edges[metadata.id].append(dep.id)
                self.reverse_edges[dep.id].append(metadata.id)

    def get_dependencies(self, plugin_id: str) -> list[str]:
        """Get direct dependencies."""
        return self.edges.get(plugin_id, [])

    def get_dependents(self, plugin_id: str) -> list[str]:
        """Get plugins that depend on this one."""
        return self.reverse_edges.get(plugin_id, [])

    def has_cycle(self) -> list[str] | None:
        """Detect circular dependencies.

        Returns:
            Cycle path if found, None otherwise
        """
        visited = set()
        rec_stack = set()
        parent = {}

        def dfs(node: str) -> list[str] | None:
            """A recursive function to detect cycle in the graph.

            :param node:
            :return:
            """
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.edges.get(node, []):
                if neighbor not in visited:
                    parent[neighbor] = node
                    cycle = dfs(neighbor)
                    if cycle:
                        return cycle
                elif neighbor in rec_stack:
                    # Found cycle - reconstruct path
                    cycle = [neighbor]
                    current = node
                    while current != neighbor:
                        cycle.append(current)
                        current = parent[current]
                    cycle.append(neighbor)
                    return list(reversed(cycle))

            rec_stack.remove(node)
            return None

        for node in self.nodes:
            if node not in visited:
                cycle = dfs(node)
                if cycle:
                    return cycle

        return None

    def topological_sort(self) -> list[str]:
        """Get load order (topological sort).

        Returns:
            List of plugin IDs in load order

        Raises:
            DependencyCycleError: If circular dependency detected
        """
        # Check for cycles first
        cycle = self.has_cycle()
        if cycle:
            raise DependencyCycleError(
                f"Circular dependency: {' → '.join(cycle)}"
            )

        # Kahn's algorithm
        in_degree = dict.fromkeys(self.nodes, 0)
        for node in self.nodes:
            for neighbor in self.edges.get(node, []):
                in_degree[neighbor] += 1

        queue = deque([
            node for node, degree in in_degree.items() if degree == 0
        ])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)

            for neighbor in self.edges.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result


class DependencyResolver:
    """Resolve plugin dependencies."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry

    async def resolve(
            self, plugins: list[PluginMetadata]
    ) -> tuple[list[str], list[str]]:
        """Resolve dependencies and return load order.

        Args:
            plugins: List of plugin metadata

        Returns:
            Tuple of (load_order, warnings)

        Raises:
            DependencyError: If dependencies cannot be resolved
        """
        graph = DependencyGraph()
        warnings = []

        # Add all plugins to graph
        for plugin in plugins:
            graph.add_plugin(plugin)

        # Validate dependencies
        for plugin in plugins:
            for dep in plugin.dependencies:
                if dep.id not in graph.nodes:
                    if dep.optional:
                        warnings.append(
                            f"Optional dependency missing: {plugin.id} → {dep.id}"
                        )
                    else:
                        raise DependencyNotFoundError(
                            f"Required dependency missing: {plugin.id} → {dep.id}"
                        )
                else:
                    # Check version compatibility
                    dep_plugin = graph.nodes[dep.id]
                    if not dep.is_satisfied_by(dep_plugin.version):
                        raise DependencyVersionError(
                            f"Version mismatch: {plugin.id} requires "
                            f"{dep.id} {dep.version}, found {dep_plugin.version}"
                        )

        # Get load order
        try:
            load_order = graph.topological_sort()
        except DependencyCycleError as e:
            raise DependencyError(f"Circular dependency detected: {e}")

        return load_order, warnings
