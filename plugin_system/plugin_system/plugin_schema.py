# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Author(BaseModel):
    """Plugin author."""

    name: str
    email: str | None = None
    url: str | None = None


class Requirements(BaseModel):
    """Plugin requirements."""

    python: str | None = None
    berg_agents: str | None = None
    system: list[str] = []


class Dependency(BaseModel):
    """Plugin dependency."""

    id: str
    version: str
    optional: bool = False
    peer: bool = False


class ToolCapability(BaseModel):
    """Tool capability."""

    type: Literal["tool"] = "tool"
    id: str
    name: str
    description: str
    tools: list[str] = []
    risk_level: Literal["low", "medium", "high"] = "medium"
    deferred: bool = True


class AgentCapability(BaseModel):
    """Agent capability."""

    type: Literal["agent"] = "agent"
    id: str
    name: str
    description: str
    complexity: Literal["simple", "medium", "complex"] = "medium"


class ProviderCapability(BaseModel):
    """Provider capability."""

    type: Literal["provider"] = "provider"
    id: str
    name: str
    models: dict[str, dict[str, Any]] = {}


class BackendCapability(BaseModel):
    """Backend capability."""

    type: Literal["backend"] = "backend"
    backend_type: str
    name: str


class LifecycleConfig(BaseModel):
    """Lifecycle configuration."""

    auto_enable: bool = False
    deferred: bool = True
    priority: int = 0


class SandboxConfig(BaseModel):
    """Sandbox configuration."""

    level: Literal["none", "process", "container"] = "process"
    constraints: dict[str, Any] = {}


class Endpoint(BaseModel):
    """HTTP endpoint provided by plugin."""

    path: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    description: str


class Hook(BaseModel):
    """Event hook."""

    event: str
    handler: str


class TestingConfig(BaseModel):
    """Testing configuration."""

    pattern: str = "tests/**/test_*.py"
    fixtures: list[str] = []


class SessionScope(BaseModel):
    """Declare that a plugin's tools take a per-session storage path.

    A plugin that keeps state per conversation (plans, notes, drafts)
    exposes a path argument that every call has to supply. Leaving that
    to the caller means the location depends on the process working
    directory and two sessions can collide — so the plugin declares the
    argument here and the plugin system binds it instead::

        ~/.berg-agents/projects/<project-id>/<subdir>/<session-key>/

    The bound argument is removed from the model-visible schema, so the
    store cannot be redirected by a model. This is deliberately a
    plugin-system concept: no core code names any plugin, and any plugin
    with per-session files can declare it.
    """

    #: Name of the tool argument that must be bound (e.g. ``todo_path``).
    parameter: str = Field(..., pattern=r"^[a-z_][a-z0-9_]*$")

    #: Folder under the project dir; the session key is one level deeper.
    subdir: str = Field(..., pattern=r"^[A-Za-z0-9._-]+$")

    #: Session-less callers (probes, first-run UI) use this folder name.
    default_key: str = Field("_default", pattern=r"^[A-Za-z0-9._-]+$")


class ToolsetConfig(BaseModel):
    """Which agent roles a plugin offers its tools to.

    Declaring no roles means chat-only, which is what every plugin meant
    before roles existed. A plugin that wants a planner or an implementer
    to use its tools opts in explicitly, so widening access is never an
    accident.
    """

    #: Roles allowed to use this plugin's tools (``chat`` is conventional).
    roles: list[str] = Field(default_factory=list, max_length=16)


class PluginManifest(BaseModel):
    """Plugin manifest."""

    # Identity
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+")
    name: str

    # Description
    description: str | None = None

    # Metadata
    author: Author | None = None
    license: str | None = None
    homepage: str | None = None
    repository: str | None = None
    tags: list[str] = []
    icon: str | None = None

    # Entry point
    entry_point: str = Field(
        ..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]+:[a-zA-Z_][a-zA-Z0-9_]+$"
    )

    # Requirements
    requirements: Requirements = Requirements()

    # Dependencies
    dependencies: list[Dependency] = []

    # Capabilities
    capabilities: list[
        ToolCapability
        | AgentCapability
        | ProviderCapability
        | BackendCapability
    ] = []

    # Settings
    settings_schema: dict[str, Any] | None = None

    # UI surface (optional): the plugin ships its own component.
    ui: dict[str, Any] | None = None

    # Per-session storage binding (see SessionScope)
    session_scope: SessionScope | None = None

    # Which agent roles may use this plugin's tools (see ToolsetConfig)
    toolset: ToolsetConfig = ToolsetConfig()

    # Permissions
    permissions: list[str | dict] = []

    # Lifecycle
    lifecycle: LifecycleConfig = LifecycleConfig()

    # Sandbox
    sandbox: SandboxConfig = SandboxConfig()

    # Endpoints
    endpoints: list[Endpoint] = []

    # Hooks
    hooks: list[Hook] = []

    # Testing
    testing: TestingConfig = TestingConfig()

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> bool | str:
        if not v.startswith("berg-plugin-"):
            import warnings

            warnings.warn(f"Plugin ID should start with 'berg-plugin-': {v}")
        return v

    def to_metadata(self, *, path: Path | None = None) -> Any:
        """Convert this manifest into the discovery record.
        This is the ONE place a manifest field becomes a
        :class:`~plugin_system.discovery.plugin_metadata.PluginMetadata`
        field. Discovery calls it instead of hand-copying keys, so a new
        manifest field cannot be validated and then silently dropped on
        the way to the runtime.

        :param path: Directory holding ``plugin.yaml`` (the record keeps
            the folder, not the file, because plugin code loads relative
            to it).
        :return: A populated ``PluginMetadata``.
        """
        from plugin_system.dependency.plugin_dependency import PluginDependency
        from plugin_system.discovery.plugin_metadata import PluginMetadata

        dependencies = [
            PluginDependency(
                id=dep.id, version=dep.version, optional=dep.optional
            )
            for dep in self.dependencies
        ]

        return PluginMetadata(
            id=self.id,
            version=self.version,
            name=self.name,
            description=self.description or "",
            source="local",
            path=path,
            entry_point=self.entry_point,
            author=self.author.name if self.author else None,
            license=self.license,
            homepage=self.homepage,
            repository=self.repository,
            tags=list(self.tags),
            icon=self.icon,
            ui=self.ui,
            dependencies=dependencies,
            permissions=list(self.permissions),
            settings_schema=self.settings_schema,
            session_scope=self.session_scope,
            toolset_roles=tuple(self.toolset.roles),
        )
