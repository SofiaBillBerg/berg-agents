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
