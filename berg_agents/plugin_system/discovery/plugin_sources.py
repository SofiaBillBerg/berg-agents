"""Plugin source enumeration."""

from enum import Enum


class PluginSource(str, Enum):
    """Plugin discovery sources."""

    BUILTIN = "builtin"
    PACKAGE = "package"
    LOCAL = "local"
    REMOTE = "remote"
