# Plugin Manifest Schema & Validation

*Generated: 2026-10-10*

## Overview

The plugin manifest defines plugin metadata, capabilities, dependencies, and configuration.
This document specifies the YAML schema, JSON Schema for validation, and Python models for parsing.

## Manifest Format

Plugins use `plugin.yaml` or `plugin.yml` in their root directory:

```
my-plugin/
├── plugin.yaml       # Main manifest
├── __init__.py       # Entry point
└── ...               # Other files
```

## YAML Schema

```yaml
# plugin.yaml - Complete schema reference

# === Identity (Required) ===
id: "berg-plugin-github"           # Unique identifier (kebab-case)
version: "1.2.3"                   # Semantic version
name: "GitHub Integration"         # Human-readable name

# === Description (Required) ===
description: |
  GitHub integration for issues, pull requests,
  repositories, and actions.

# === Metadata (Optional) ===
author:
  name: "Your Name"
  email: "you@example.com"
  url: "https://example.com"

license: "AGPL-3.0-only"                     # SPDX license identifier

homepage: "https://github.com/org/berg-plugin-github"
repository: "https://github.com/org/berg-plugin-github"

tags:                             # Category tags
  - "github"
  - "vcs"
  - "productivity"

icon: "🤖"                        # Emoji or URL

# === Entry Point (Required) ===
entry_point: "my_plugin:GitHubPlugin"

# === Requirements (Optional) ===
requirements:
  python: ">=3.10"                 # Python version constraint
  berg_agents: ">=0.5.0 <1.0.0"   # Berg agents version constraint
  
  # System requirements
  system:
    - "git"

# === Dependencies (Optional) ===
dependencies:
  # Required dependency
  - id: "berg-plugin-auth"
    version: "^1.0.0"
    optional: false
  
  # Optional dependency
  - id: "berg-plugin-notifications"
    version: ">=2.0.0"
    optional: true
  
  # Peer dependency
  - id: "berg-plugin-git"
    version: "*"
    peer: true

# === Capabilities (Optional) ===
capabilities:
  # Tool capability
  - type: tool
    id: "github_issues"
    name: "GitHub Issues"
    description: "Manage GitHub issues"
    tools:
      - "create_issue"
      - "list_issues"
      - "close_issue"
    risk_level: "medium"
    deferred: true
  
  # Agent capability
  - type: agent
    id: "github_agent"
    name: "GitHub Agent"
    description: "Agent for GitHub operations"
    complexity: "medium"
  
  # Provider capability
  - type: provider
    id: "github_models"
    name: "GitHub Models"
    models:
      copilot:
        name: "GitHub Copilot"
        options: {}
  
  # Backend capability
  - type: backend
    backend_type: "vcs"
    name: "GitHub Backend"

# === Settings Schema (Optional) ===
settings_schema:
  type: object
  properties:
    token:
      type: string
      description: "GitHub personal access token"
      secret: true
      required: true
    org:
      type: string
      description: "GitHub organization"
      default: ""
    rate_limit:
      type: integer
      minimum: 100
      maximum: 5000
      default: 1000
  required:
    - token

# === Permissions (Optional) ===
permissions:
  - filesystem:read
  - network:outbound:
      domains:
        - "api.github.com"
        - "github.com"
  - env:read:
      vars:
        - "GITHUB_TOKEN"

# === Lifecycle (Optional) ===
lifecycle:
  # Auto-enable on load
  auto_enable: false
  
  # Deferred loading (default: true)
  deferred: true
  
  # Priority (higher loads first)
  priority: 100

# === Sandbox (Optional) ===
sandbox:
  # Override default sandbox level
  level: "process"
  
  # Additional constraints
  constraints:
    memory_mb: 512
    cpu_percent: 50
    network: true

# === Endpoints (Optional) ===
endpoints:
  # HTTP endpoints provided by plugin
  - path: "/webhook/github"
    method: "POST"
    description: "GitHub webhook receiver"

# === Hooks (Optional) ===
hooks:
  # Custom hooks
  - event: "agent.task.completed"
    handler: "my_plugin:on_task_completed"

# === Testing (Optional) ===
testing:
  # Test files pattern
  pattern: "tests/**/test_*.py"
  
  # Fixtures
  fixtures:
    - "tests/fixtures/github"
```

## [JSON Schema](../plugin-manifest.json)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://berg-agents.dev/schemas/plugin-manifest.json",
  "title": "Berg Agents Plugin Manifest",
  "description": "Schema for Berg Agents plugin manifest",
  "type": "object",
  "required": ["id", "version", "name", "description", "entry_point"],
  "properties": {
    "id": {
      "type": "string",
      "pattern": "^[a-z0-9][a-z0-9-]*$",
      "minLength": 3,
      "maxLength": 64,
      "examples": ["berg-plugin-github"]
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+(-[a-zA-Z0-9.]+)?(\\+[a-zA-Z0-9.]+)?$"
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 100
    },
    "description": {
      "oneOf": [
        {"type": "string"},
        {"type": "null"}
      ]
    },
    "author": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "email": {"type": "string", "format": "email"},
        "url": {"type": "string", "format": "uri"}
      }
    },
    "license": {
      "type": "string",
      "pattern": "^[A-Za-z0-9.-]+$"
    },
    "homepage": {
      "type": "string",
      "format": "uri"
    },
    "repository": {
      "type": "string",
      "format": "uri"
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"}
    },
    "icon": {
      "type": "string"
    },
    "entry_point": {
      "type": "string",
      "pattern": "^[a-zA-Z_][a-zA-Z0-9_.]+:[a-zA-Z_][a-zA-Z0-9_]+$"
    },
    "requirements": {
      "type": "object",
      "properties": {
        "python": {"type": "string"},
        "berg_agents": {"type": "string"},
        "system": {
          "type": "array",
          "items": {"type": "string"}
        }
      }
    },
    "dependencies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "version"],
        "properties": {
          "id": {"type": "string"},
          "version": {"type": "string"},
          "optional": {"type": "boolean"},
          "peer": {"type": "boolean"}
        }
      }
    },
    "capabilities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type"],
        "properties": {
          "type": {"enum": ["tool", "agent", "provider", "backend"]},
          "id": {"type": "string"},
          "name": {"type": "string"},
          "description": {"type": "string"},
          "risk_level": {"enum": ["low", "medium", "high"]},
          "deferred": {"type": "boolean"}
        }
      }
    },
    "settings_schema": {
      "$ref": "#/definitions/jsonSchema"
    },
    "permissions": {
      "type": "array",
      "items": {
        "oneOf": [
          {"type": "string"},
          {"type": "object"}
        ]
      }
    },
    "lifecycle": {
      "type": "object",
      "properties": {
        "auto_enable": {"type": "boolean"},
        "deferred": {"type": "boolean"},
        "priority": {"type": "integer", "minimum": 0}
      }
    }
  },
  "definitions": {
    "jsonSchema": {
      "type": "object"
    }
  }
}
```

## [Python Models](../plugin_schema.py)

```python
from typing import Literal

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
```

## Validation

### [Validation Functions](../plugin_validation.py)

```python
from pathlib import Path

from jsonschema import ValidationError as JsonValidationError
from jsonschema import validate
from pydantic import ValidationError as PydanticValidationError
import yaml


class ManifestValidator:
    """Validate plugin manifest."""

    def __init__(self) -> None:
        self.schema = self._load_schema()

    def _load_schema(self) -> dict:
        """Load JSON schema."""
        # Would load from file or embed
        return {}  # Placeholder

    async def validate_file(
        self, path: Path
    ) -> tuple[PluginManifest, list[str]]:
        """Validate manifest file.

        Returns:
            Tuple of (validated manifest, warnings)
        """
        warnings = []

        # Read file
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ManifestError(f"Failed to parse YAML: {e}")

        # Validate with Pydantic
        try:
            manifest = PluginManifest(**data)
        except PydanticValidationError as e:
            raise ManifestError(f"Invalid manifest: {e}")

        # Validate JSON schema
        try:
            validate(instance=data, schema=self.schema)
        except JsonValidationError as e:
            warnings.append(f"Schema warning: {e.message}")

        # Additional checks
        await self._validate_dependencies(manifest, warnings)
        await self._validate_entry_point(manifest, warnings)

        return manifest, warnings

    async def _validate_dependencies(
        self, manifest: PluginManifest, warnings: list[str]
    ) -> None:
        """Validate dependencies are available."""
        for dep in manifest.dependencies:
            if dep.optional:
                continue
            # Would check registry for dependency

    async def _validate_entry_point(
        self, manifest: PluginManifest, warnings: list[str]
    ) -> None:
        """Validate entry point exists."""
        module_path, class_name = manifest.entry_point.rsplit(":", 1)

        try:
            module = importlib.import_module(module_path)
            if not hasattr(module, class_name):
                warnings.append(f"Entry point class not found: {class_name}")
        except ImportError:
            warnings.append(f"Entry point module not found: {module_path}")


class ManifestError(Exception):
    """Manifest validation error."""
```

### CLI Validation

```bash
# Validate plugin manifest
$ berg-agents plugin validate ./my-plugin/plugin.yaml

# Validate and show parsed result
$ berg-agents plugin validate ./my-plugin/plugin.yaml --verbose
```

## Migration from Old Format

If you have existing plugins using old formats:

```yaml
# Old format (deprecated)
name: "My Plugin"
version: "1.0"
entry: "my_plugin:Plugin"

# New format
id: "berg-plugin-my-plugin"
version: "1.0.0"
name: "My Plugin"
entry_point: "my_plugin:Plugin"
```

Migration tool:

```bash
# Auto-migrate old manifest to new format
$ berg-agents plugin migrate ./my-plugin/
```

## Summary

**Manifest format:** YAML with full schema support

**Key features:**
- JSON Schema for validation [JSON schema](../plugin-manifest.json)
- Pydantic models for parsing [Schema model](../plugin_schema.py), [Validation](../plugin_validation.py)
- Comprehensive metadata
- Capability definitions
- Permission declarations
- Version constraints
- CLI validation tool
- Migration from old formats
