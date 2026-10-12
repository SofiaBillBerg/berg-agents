"""Module for plugin metadata."""
# Plugin Metadata

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from berg_agents.plugin_system.dependency.plugin_dependency import (
    PluginDependency,
)
from berg_agents.plugin_system.discovery.plugin_sources import (
    PluginSource,
)


@dataclass
class PluginMetadata:
    """Plugin discovery metadata."""

    # Identity
    id: str  # Unique identifier
    version: str  # Semantic version
    name: str  # Human-readable name
    description: str  # Brief description

    # Location
    source: PluginSource  # "builtin", "package", "local", "remote"
    path: Path | None  # Filesystem path (if applicable)
    entry_point: str  # Python import path

    # Metadata
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    repository: str | None = None
    tags: list[str] = field(default_factory=list)
    icon: str | None = None

    # Requirements
    dependencies: list[PluginDependency] = field(default_factory=list)
    python_requires: str | None = None
    berg_agents_requires: str | None = None

    # Configuration
    settings_schema: dict[str, Any] | None = None
    permissions: list[str] = field(default_factory=list)

    # Behavior
    deferred: bool = True  # Enable deferred loading
    auto_enable: bool = False  # Enable on load

    # Runtime state
    enabled: bool = False
    loaded: bool = False
    error: Exception | None = None
