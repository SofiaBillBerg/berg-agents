"""Dependency management for the plugin system."""

import logging
from collections import defaultdict

from berg_agents.plugin_system.dependency.version_parsing import (
    Version,
    VersionConstraint,
)
from berg_agents.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
)
from berg_agents.plugin_system.discovery.plugin_registry import (
    PluginRegistry,
)
from berg_agents.plugin_system.exceptions import (
    DependencyCycleError,
    DependencyError,
    DependencyNotFoundError,
    DependencyVersionError,
    VersionConflictError,
)

logger = logging.getLogger(__name__)


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
            """Depth-first search to detect cycles."""
            visited.add(node)
            rec_stack.add(node)

            for neighbor in self.edges.get(node, []):
                if neighbor not in visited:
                    parent[neighbor] = node
                    cycle: list[str] | None = dfs(neighbor)
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
            raise DependencyCycleError(f"Circular dependency: {' -> '.join(cycle)}")

        # Kahn's algorithm
        from collections import deque
        in_degree = dict.fromkeys(self.nodes, 0)
        for node in self.nodes:
            for neighbor in self.edges.get(node, []):
                in_degree[neighbor] += 1

        queue = deque([node for node, degree in in_degree.items() if degree == 0])
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
            self,
            plugins: list[PluginMetadata],
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
                            f"Optional dependency missing: {plugin.id} -> {dep.id}"
                        )
                    else:
                        raise DependencyNotFoundError(
                            f"Required dependency missing: {plugin.id} -> {dep.id}"
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


class ConflictResolver:
    """Resolve version conflicts."""

    def resolve_conflicts(
            self,
            plugins: list[PluginMetadata],
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
        by_id: dict[str, list[PluginMetadata]] = defaultdict(list)
        for plugin in plugins:
            by_id[plugin.id].append(plugin)

        resolved = []

        for plugin_id, versions in by_id.items():
            if len(versions) == 1:
                resolved.append(versions[0])
                continue

            # Multiple versions - find highest compatible
            candidates = sorted(
                versions,
                key=lambda p: Version.parse(p.version),
                reverse=True,
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
