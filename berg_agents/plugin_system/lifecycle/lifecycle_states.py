from enum import StrEnum


class PluginState(StrEnum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"  # Found but not loaded
    LOADING = "loading"  # Import in progress
    LOADED = "loaded"  # Manifest parsed, code imported
    ENABLING = "enabling"  # Activation in progress
    ENABLED = "enabled"  # Active and available
    DISABLING = "disabling"  # Deactivation in progress
    DISABLED = "disabled"  # Present but inactive
    UNLOADING = "unloading"  # Cleanup in progress
    ERROR = "error"  # Failed to load or crashed
    DEPRECATED = "deprecated"  # Marked for removal
