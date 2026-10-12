"""Plugin dependency specification."""

from dataclasses import dataclass

from berg_agents.plugin_system.dependency.version_parsing import (
    Version,
    VersionConstraint,
)


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
