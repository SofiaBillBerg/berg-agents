# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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
    def validate_id(cls, v: str) -> str:
        if not v.startswith("berg-plugin-"):
            import warnings

            warnings.warn(f"Plugin ID should start with 'berg-plugin-': {v}")
        return v
