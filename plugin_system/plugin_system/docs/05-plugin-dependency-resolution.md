# Plugin Dependency Resolution & Version Management

*Generated: 2026-10-10*

## Overview

The dependency resolution system ensures plugins load in the correct order, with compatible versions, and handles circular dependencies, conflicts, and optional dependencies.

## Version Specifications

### Semantic Versioning

Follow SemVer 2.0.0: `MAJOR.MINOR.PATCH`

- **MAJOR** - Breaking changes
- **MINOR** - New features, backward compatible
- **PATCH** - Bug fixes, backward compatible

### Version Constraints

Support npm/cargo-style version constraints:

```yaml
dependencies:
  # Exact version
  - id: berg-plugin-github
    version: "1.2.3"
  
  # Range (>= and <)
  - id: berg-plugin-jira
    version: ">=1.0.0 <2.0.0"
  
  # Caret (compatible, allows MINOR/PATCH bumps)
  - id: berg-plugin-slack
    version: "^1.2.0"    # >=1.2.0 <2.0.0
  
  # Tilde (allows PATCH bumps only)
  - id: berg-plugin-discord
    version: "~1.2.3"    # >=1.2.3 <1.3.0
  
  # Wildcard
  - id: berg-plugin-utils
    version: "1.2.*"     # >=1.2.0 <1.3.0
  
  # Any version
  - id: berg-plugin-helpers
    version: "*"
```

### [Version Parsing](../dependency/version_parsing.py)

```python
from dataclasses import dataclass
import re


@dataclass
class Version:
    """Semantic version."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    @classmethod
    def parse(cls, version_string: str) -> "Version":
        """Parse version string."""
        pattern = r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-.]+))?(?:\+([0-9A-Za-z-.]+))?$"
        match = re.match(pattern, version_string)

        if not match:
            raise ValueError(f"Invalid version: {version_string}")

        major, minor, patch, prerelease, build = match.groups()

        return cls(
            major=int(major),
            minor=int(minor),
            patch=int(patch),
            prerelease=prerelease,
            build=build,
        )

    def __str__(self) -> str:
        v = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            v += f"-{self.prerelease}"
        if self.build:
            v += f"+{self.build}"
        return v

    def __lt__(self, other: "Version") -> bool:
        """Compare versions."""
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        if self.patch != other.patch:
            return self.patch < other.patch

        # Prerelease versions have lower precedence
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and other.prerelease:
            return self.prerelease < other.prerelease

        return False

    def satisfies(self, constraint: str) -> bool:
        """Check if version satisfies constraint."""
        return VersionConstraint.parse(constraint).matches(self)


class VersionConstraint:
    """Version constraint matcher."""

    def __init__(self, constraint_str: str) -> None:
        self.constraint_str = constraint_str
        self.matchers = self._parse(constraint_str)

    @classmethod
    def parse(cls, constraint_str: str) -> "VersionConstraint":
        """Parse constraint string."""
        return cls(constraint_str)

    def _parse(self, constraint: str) -> list[callable]:
        """Parse constraint into matcher functions."""
        constraint = constraint.strip()

        # Wildcard
        if constraint == "*":
            return [lambda v: True]

        # Caret (^1.2.3 → >=1.2.3 <2.0.0)
        if constraint.startswith("^"):
            base = Version.parse(constraint[1:])
            return [lambda v: v >= base, lambda v: v.major == base.major]

        # Tilde (~1.2.3 → >=1.2.3 <1.3.0)
        if constraint.startswith("~"):
            base = Version.parse(constraint[1:])
            return [
                lambda v: v >= base,
                lambda v: v.major == base.major and v.minor == base.minor]

        # Range (>=1.0.0 <2.0.0)
        if " " in constraint:
            parts = constraint.split()
            matchers = []
            for part in parts:
                matchers.extend(self._parse(part))
            return matchers

        # Comparison operators
        for op in [">=", "<=", ">", "<", "="]:
            if constraint.startswith(op):
                version = Version.parse(constraint[len(op) :])
                if op == ">=":
                    return [lambda v: v >= version]
                elif op == "<=":
                    return [lambda v: v <= version]
                elif op == ">":
                    return [lambda v: v > version]
                elif op == "<":
                    return [lambda v: v < version]
                elif op == "=":
                    return [lambda v: v == version]

        # Exact version
        version = Version.parse(constraint)
        return [lambda v: v == version]

    def matches(self, version: Version) -> bool:
        """Check if version matches constraint."""
        return all(matcher(version) for matcher in self.matchers)
```

## Dependency Declaration

### Plugin Manifest

```yaml
# plugin.yaml
id: berg-plugin-github
version: 1.2.0

dependencies:
  # Required dependency
  - id: berg-plugin-auth
    version: "^1.0.0"
    optional: false
  
  # Optional dependency
  - id: berg-plugin-notifications
    version: ">=2.0.0"
    optional: true
  
  # Peer dependency (must be present but not managed)
  - id: berg-plugin-git
    version: "*"
    peer: true

# Python version constraint
python_requires: ">=3.10"

# Berg agents version constraint
berg_agents_requires: ">=0.1.0 <1.0.0"
```

### [Dependency Types](../dependency/dependency_management.py)

```python
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
```

## Dependency Resolution Algorithm

### [Dependency Graph](../dependency/dependency_management.py)

```python
from collections import defaultdict, deque


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
```

## Conflict Resolution

### [Version Conflicts](../dependency/dependency_resolver.py)

```python
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
```

## [Load Order Calculation](../dependency/dependency_resolver.py)

```python
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
        DependencyGraph()
        for plugin_id in load_order:
            # Would need access to metadata here
            pass

        # Sort by priority within dependency constraints
        # This is a topological sort with priority as secondary key
        # (Implementation would go here)

        return load_order
```

## [Runtime Dependency Checking](../dependencyver.py)

```python
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
```

## [Plugin API Versioning](../dependencyver.py)

```python
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
    ),
    PluginAPIVersion(
        version="1.1.0",
        added=["health_check", "EventBus"],
        deprecated=["legacy_hook"],
    )]


def check_api_compatibility(
    plugin_api_version: str, current_version: str
) -> bool:
    """Check if plugin API version is compatible."""
    plugin_ver = Version.parse(plugin_api_version)
    current_ver = Version.parse(current_version)

    # Same major version = compatible
    return plugin_ver.major == current_ver.major
```

## Configuration

```yaml
# .berg-agents/bergagents.yaml
plugins:
  dependency_resolution:
    # Strategy: "strict" | "best-effort"
    strategy: "strict"
    
    # Allow optional dependencies to be missing
    allow_missing_optional: true
    
    # Auto-enable dependencies
    auto_enable_deps: true
    
    # Max dependency depth
    max_depth: 10
    
    # Conflict resolution: "highest" | "lowest" | "fail"
    conflict_resolution: "highest"
```

## Summary

**Version constraints:** Exact, range, caret, tilde, wildcard

**Resolution:** Dependency graph → cycle detection → topological sort → load order

**Key features:**
- Semantic versioning
- Circular dependency detection
- Version conflict resolution
- Optional dependencies
- Peer dependencies
- Runtime dependency checking
- API versioning

**Next:** Security and sandboxing model
