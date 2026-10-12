class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class VersionConflictError(Exception):
    """Class for version conflict errors."""


class DependencyVersionError(Exception):
    """Checks dependency versions for errors."""


class DependencyCycleError(Exception):
    """Checks cycle error in dependencies."""


class PluginNotFoundError(Exception):
    """Class to yield error if plugin is not found."""


class DependencyNotFoundError(Exception):
    """Class to check dependency not found"""


class DependencyError(Exception):
    """Class for dependency errors."""


class DependencyNotEnabledError(Exception):
    """Class for dependency not enabled errors."""


class PluginError(Exception):
    """Custom exception for plugin errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PluginStateError(Exception):
    """Raised when a plugin is in an invalid state for the requested operation."""


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""


class PluginEnableError(Exception):
    """Raised when a plugin fails to enable."""


class ManifestError(Exception):
    """Manifest validation error."""


class PermissionDeniedError(Exception):
    """Raised when a plugin attempts an unauthorized operation."""

    def __init__(
            self, message: str, plugin_id: str = "", resource: str = ""
    ) -> None:
        super().__init__(message)
        self.message = message
        self.plugin_id = plugin_id
        self.resource = resource


# Missing exception classes that lifecycle_hooks.py expects
class HealthStatus:
    """Health status for plugins - stub class, real one in runtime_health"""


class PluginUnloadError(Exception):
    """Raised when a plugin fails to unload."""
