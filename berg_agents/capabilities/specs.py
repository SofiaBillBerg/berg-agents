"""Config-driven presets for toolsets and capabilities.

This module holds the *schema* layer of the presets refactor (Phase 1):
typed Pydantic models describing which toolsets and harness capabilities
apply to a given model / agent combination. It changes no runtime
behavior on its own — :mod:`berg_agents.capabilities.spec_loader`
resolves these specs against a raw config mapping.

Config shapes (all optional, all additive — old keys keep working)::

    "toolsets": {
        "default": ["read-only"],          # toolset names enabled everywhere
        "builtin": {"read-only": {...}},   # shipped toolset definitions
        "custom": {"my-tools": {...}},     # user-defined toolset definitions
    },
    "capabilities": {
        "default": ["filesystem", "shell"],# capability ids enabled everywhere
        "custom": {"memory": {"agent_name": "main"}},
    },
    "presets": [                           # per-model / per-agent overrides
        {"name": "standard-readonly", "models": ["*qwen*"],
         "agents": ["implementation"], "toolsets": ["read-only"],
         "capabilities": ["filesystem"]},
    ]
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolsetSpec(BaseModel):
    """One named toolset: include / exclude tool names or globs.

    Attributes:
        name: Stable toolset name referenced from presets, e.g. ``"read-only"``.
        includes: Tool names or glob patterns (``"read_*"``, ``"mcp_*"``).
            Empty means "no explicit includes" (not "include everything").
        excludes: Tool names or globs removed after includes are applied.
        builtin: True for shipped toolsets, False for user-defined ones.
        description: Human-readable summary of what the toolset is for.
    """

    name: str
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    builtin: bool = False
    description: str = ""


class CapabilitySpec(BaseModel):
    """One harness capability with its constructor options.

    Attributes:
        id: Capability id, e.g. ``"filesystem"``, ``"shell"``, ``"memory"``.
            Dashes and underscores are treated as equivalent on lookup.
        enabled: When False the capability is skipped during resolution.
        options: Keyword arguments forwarded to the harness capability
            constructor (unknown keys are ignored, never an error).
        defer_loading: When True the capability is lazily attached via the
            harness ``defer_loading`` hook instead of at agent build time.
    """

    id: str
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)
    defer_loading: bool = False


class PresetSpec(BaseModel):
    """Named per-model / per-agent selection of toolsets + capabilities.

    A preset matches when *both* selectors match: an empty ``models`` list
    matches every model, an empty ``agents`` list matches every agent.

    Attributes:
        name: Stable preset name, e.g. ``"standard-readonly"``.
        models: Glob patterns matched against the model id (``"*qwen*"``).
        agents: Agent names matched exactly (``"implementation"``).
        toolsets: Toolset names merged into the resolved selection.
        capabilities: Capability ids merged into the resolved selection.
    """

    name: str
    models: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    toolsets: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
