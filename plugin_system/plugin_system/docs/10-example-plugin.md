# Example Plugin Implementation

*Generated: 2026-10-10*

## Overview

This document provides a complete example of a berg_agents plugin, demonstrating all key features: manifest, plugin class, capabilities, configuration, events, and lifecycle hooks.

## Project Structure

```
example-github-plugin/
├── plugin.yaml              # Manifest
├── __init__.py              # Package init
├── github_plugin.py         # Main plugin class
├── tools.py                 # Tool implementations
├── tools_schema.py          # Pydantic schemas for tools
├── config.py                # Configuration model
└── tests/
    ├── __init__.py
    └── test_plugin.py       # Unit tests
```

## 1. Plugin Manifest

```yaml
# plugin.yaml
id: berg-plugin-github
version: 1.0.0
name: GitHub Integration
description: |
  GitHub integration for issues, pull requests,
  repositories, and actions.

author:
  name: "Berg Agents Team"
  email: "team@berg-agents.dev"
  url: "https://berg-agents.dev"

license: AGPL-3.0-only
homepage: https://github.com/berg-agents/plugin-github
repository: https://github.com/berg-agents/plugin-github

tags:
  - github
  - vcs
  - productivity

icon: "🐙"

entry_point: github_plugin:GitHubPlugin

requirements:
  python: ">=3.10"
  berg_agents: ">=0.5.0 <1.0.0"
  system:
    - git

dependencies:
  - id: berg-plugin-auth
    version: "^1.0.0"
    optional: false
  - id: berg-plugin-notifications
    version: ">=2.0.0"
    optional: true

capabilities:
  - type: tool
    id: github_issues
    name: GitHub Issues
    description: Manage GitHub issues
    tools:
      - create_issue
      - list_issues
      - close_issue
      - get_issue
    risk_level: medium
    deferred: true
  
  - type: tool
    id: github_prs
    name: GitHub Pull Requests
    description: Manage pull requests
    tools:
      - create_pr
      - list_prs
      - merge_pr
    risk_level: medium
    deferred: true
  
  - type: tool
    id: github_repos
    name: GitHub Repositories
    description: Manage repositories
    tools:
      - create_repo
      - list_repos
      - get_repo
    risk_level: high
    deferred: false

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
      description: "GitHub organization (optional)"
      default: ""
    default_repo:
      type: string
      description: "Default repository for operations"
      default: ""
    rate_limit:
      type: integer
      description: "API rate limit override"
      minimum: 100
      maximum: 5000
      default: 1000
    cache_ttl:
      type: integer
      description: "Cache TTL in seconds"
      default: 300
    auto_comment:
      type: boolean
      description: "Auto-comment on PRs"
      default: false

permissions:
  - network:outbound:
      domains:
        - "api.github.com"
        - "github.com"
  - env:read:
      vars:
        - "GITHUB_TOKEN"
  - filesystem:read
  - filesystem:write:
      paths:
        - "docs/**"
        - "README.md"

lifecycle:
  auto_enable: false
  deferred: true
  priority: 100
```

## 2. Configuration Model

```python
# config.py
from pydantic import BaseModel, Field, SecretStr


class GitHubSettings(BaseModel):
    """GitHub plugin settings."""

    token: SecretStr = Field(..., description="GitHub personal access token")
    org: str = Field(default="", description="GitHub organization")
    default_repo: str = Field(default="", description="Default repository")
    rate_limit: int = Field(
        default=1000, ge=100, le=5000, description="API rate limit"
    )
    cache_ttl: int = Field(
        default=300, ge=0, le=3600, description="Cache TTL in seconds"
    )
    auto_comment: bool = Field(default=False, description="Auto-comment on PRs")

    class Config:
        json_schema_extra = {"required": ["token"]}
```

## 3. Tool Schemas

```python
# tools_schema.py
from pydantic import BaseModel, Field
from typing import Literal


class CreateIssueInput(BaseModel):
    """Input for creating an issue."""

    repo: str = Field(..., description="Repository name (org/repo)")
    title: str = Field(..., min_length=1, max_length=256)
    body: str = Field(default="", max_length=65536)
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)


class CreateIssueOutput(BaseModel):
    """Output from creating an issue."""

    id: int
    number: int
    url: str
    title: str


class ListIssuesInput(BaseModel):
    """Input for listing issues."""

    repo: str = Field(..., description="Repository name")
    state: Literal["open", "closed", "all"] = "open"
    labels: list[str] = Field(default_factory=list)
    limit: int = Field(default=30, ge=1, le=100)


class ListIssuesOutput(BaseModel):
    """Output from listing issues."""

    issues: list[dict]


class CloseIssueInput(BaseModel):
    """Input for closing an issue."""

    repo: str = Field(...)
    issue_number: int = Field(..., alias="issue_number")
    comment: str = Field(default="")

    class Config:
        populate_by_name = True
```

## 4. Tool Implementations

```python
# tools.py
import httpx
import logging
from typing import Any

from .config import GitHubSettings
from .tools_schema import (
    CreateIssueInput,
    CreateIssueOutput,
    ListIssuesInput,
    ListIssuesOutput,
    CloseIssueInput,
)

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API client."""

    def __init__(self, settings: GitHubSettings):
        self.settings = settings
        self.base_url = "https://api.github.com"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.settings.token.get_secret_value()}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "berg-agents-github-plugin"},
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_issue(
        self,
        repo: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub issue."""
        client = await self._get_client()

        data = {
            "title": title,
            "body": body}

        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees

        response = await client.post(f"/repos/{repo}/issues", json=data)
        response.raise_for_status()

        return response.json()

    async def list_issues(
        self,
        repo: str,
        state: str = "open",
        labels: list[str] | None = None,
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """List GitHub issues."""
        client = await self._get_client()

        params = {"state": state, "per_page": per_page}
        if labels:
            params["labels"] = ",".join(labels)

        response = await client.get(f"/repos/{repo}/issues", params=params)
        response.raise_for_status()

        return response.json()

    async def close_issue(
        self, repo: str, issue_number: int, comment: str = ""
    ) -> dict[str, Any]:
        """Close a GitHub issue."""
        client = await self._get_client()

        # Add comment if provided
        if comment:
            await client.post(
                f"/repos/{repo}/issues/{issue_number}/comments",
                json={"body": comment},
            )

        # Close issue
        response = await client.patch(
            f"/repos/{repo}/issues/{issue_number}", json={"state": "closed"}
        )
        response.raise_for_status()

        return response.json()


# Tool function decorators
async def create_issue(
    settings: GitHubSettings, input_data: CreateIssueInput
) -> CreateIssueOutput:
    """Create a GitHub issue."""
    client = GitHubClient(settings)

    try:
        result = await client.create_issue(
            repo=input_data.repo,
            title=input_data.title,
            body=input_data.body,
            labels=input_data.labels,
            assignees=input_data.assignees,
        )

        return CreateIssueOutput(
            id=result["id"],
            number=result["number"],
            url=result["html_url"],
            title=result["title"],
        )
    finally:
        await client.close()


async def list_issues(
    settings: GitHubSettings, input_data: ListIssuesInput
) -> ListIssuesOutput:
    """List GitHub issues."""
    client = GitHubClient(settings)

    try:
        results = await client.list_issues(
            repo=input_data.repo,
            state=input_data.state,
            labels=input_data.labels,
            per_page=input_data.limit,
        )

        issues = [
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "url": i["html_url"]}
            for i in results
            if not i.get("pull_request")  # Filter out PRs
        ]

        return ListIssuesOutput(issues=issues)
    finally:
        await client.close()


async def close_issue(
    settings: GitHubSettings, input_data: CloseIssueInput
) -> dict[str, Any]:
    """Close a GitHub issue."""
    client = GitHubClient(settings)

    try:
        result = await client.close_issue(
            repo=input_data.repo,
            issue_number=input_data.issue_number,
            comment=input_data.comment,
        )

        return {"success": True, "url": result["html_url"]}
    finally:
        await client.close()
```

## 5. Main Plugin Class

```python
# github_plugin.py
import logging
from pathlib import Path
from typing import Any

from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import ToolCapability
from berg_agents.plugins.config import GitHubSettings

from .config import GitHubSettings as SettingsModel
from .tools import create_issue, list_issues, close_issue

logger = logging.getLogger(__name__)


class GitHubPlugin(BergPlugin):
    """GitHub integration plugin."""

    def __init__(self):
        self._settings: SettingsModel | None = None
        self._github_client = None

    # === Lifecycle Hooks ===

    async def on_load(self, context: PluginContext) -> None:
        """Initialize plugin."""
        logger.info(f"Loading GitHub plugin v{context.plugin_version}")

        # Get settings
        settings_data = context.settings

        # Override with environment variable
        import os

        if token := os.environ.get("GITHUB_TOKEN"):
            settings_data = {**settings_data, "token": token}

        # Parse and validate settings
        self._settings = SettingsModel(**settings_data)

        logger.info(
            f"GitHub plugin configured for org: {self._settings.org or 'personal'}"
        )

    async def on_enable(self, context: PluginContext) -> None:
        """Enable plugin and register capabilities."""
        logger.info("Enabling GitHub plugin")

        # Subscribe to events
        self.subscribe("agent.task.completed", self._on_task_completed)

        # Emit enabled event
        await self.emit("plugin.github.enabled", {"org": self._settings.org})

    async def on_disable(self, context: PluginContext) -> None:
        """Disable plugin."""
        logger.info("Disabling GitHub plugin")

        # Close client
        if self._github_client:
            await self._github_client.close()
            self._github_client = None

    async def on_unload(self, context: PluginContext) -> None:
        """Clean up on unload."""
        logger.info("Unloading GitHub plugin")

        if self._github_client:
            await self._github_client.close()

    async def on_error(self, context: PluginContext, error: Exception) -> None:
        """Handle errors."""
        logger.error(f"GitHub plugin error: {error}", exc_info=True)

        # Emit error event
        await self.emit(
            "plugin.github.error",
            {"error": str(error), "type": type(error).__name__},
        )

    # === Capabilities ===

    def get_capabilities(self) -> list[ToolCapability]:
        """Return plugin capabilities."""
        if not self._settings:
            return []

        return [
            ToolCapability(
                type="tool",
                tool=create_issue,
                risk_level="medium",
                deferred=True,
            ),
            ToolCapability(
                type="tool", tool=list_issues, risk_level="low", deferred=True
            ),
            ToolCapability(
                type="tool",
                tool=close_issue,
                risk_level="medium",
                deferred=True,
            )]

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return settings schema."""
        return SettingsModel.model_json_schema()

    # === Event Handlers ===

    async def _on_task_completed(self, event: Event) -> None:
        """Handle task completion events."""
        task_data = event.data

        # Auto-create issue if configured
        if self._settings.auto_comment and task_data.get("result") == "failed":
            logger.info(
                f"Task failed, would create issue: {task_data.get('task_id')}"
            )
            # Implementation would create issue here

    # === Health Check ===

    async def health_check(self, context: PluginContext) -> HealthStatus:
        """Check plugin health."""
        if not self._settings:
            return HealthStatus(
                status="unhealthy", message="Plugin not configured"
            )

        try:
            # Would make API call to check
            return HealthStatus(status="healthy")
        except Exception as e:
            return HealthStatus(status="degraded", message=f"API error: {e}")


# Health status import
from berg_agents.plugins.health import HealthStatus
from berg_agents.events import Event
```

## 6. Package Init

```python
# __init__.py
"""GitHub plugin for Berg Agents."""

from .github_plugin import GitHubPlugin

__all__ = ["GitHubPlugin"]
```

## 7. Unit Tests

```python
# tests/test_plugin.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from github_plugin import GitHubPlugin
from config import GitHubSettings
from tools_schema import CreateIssueInput


@pytest.fixture
def mock_context():
    """Create mock plugin context."""
    context = MagicMock()
    context.plugin_id = "berg-plugin-github"
    context.plugin_version = "1.0.0"
    context.settings = {
        "token": "test-token",
        "org": "test-org",
        "default_repo": "test-repo",
        "rate_limit": 1000,
        "cache_ttl": 300,
        "auto_comment": False}
    context.event_bus = AsyncMock()
    context.app = MagicMock()
    return context


@pytest.fixture
def settings():
    """Create test settings."""
    return GitHubSettings(
        token="test-token", org="test-org", default_repo="test-repo"
    )


class TestGitHubPlugin:
    """Test GitHub plugin."""

    @pytest.mark.asyncio
    async def test_on_load(self, mock_context):
        """Test plugin loads with settings."""
        plugin = GitHubPlugin()

        await plugin.on_load(mock_context)

        assert plugin._settings is not None
        assert plugin._settings.org == "test-org"

    @pytest.mark.asyncio
    async def test_on_enable(self, mock_context):
        """Test plugin enables correctly."""
        plugin = GitHubPlugin()
        await plugin.on_load(mock_context)

        await plugin.on_enable(mock_context)

        # Check event emitted
        mock_context.event_bus.emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_capabilities(self, mock_context):
        """Test plugin returns capabilities."""
        plugin = GitHubPlugin()
        await plugin.on_load(mock_context)

        capabilities = plugin.get_capabilities()

        assert len(capabilities) == 3
        assert all(c.type == "tool" for c in capabilities)

    @pytest.mark.asyncio
    async def test_health_check(self, mock_context):
        """Test health check."""
        plugin = GitHubPlugin()
        await plugin.on_load(mock_context)

        health = await plugin.health_check(mock_context)

        assert health.status in ("healthy", "degraded")


class TestConfig:
    """Test configuration."""

    def test_settings_defaults(self):
        """Test default values."""
        settings = GitHubSettings(token="test")

        assert settings.rate_limit == 1000
        assert settings.cache_ttl == 300
        assert settings.auto_comment is False

    def test_settings_with_org(self):
        """Test settings with organization."""
        settings = GitHubSettings(
            token="test", org="myorg", default_repo="myrepo"
        )

        assert settings.org == "myorg"
        assert settings.default_repo == "myrepo"
```

## 8. Package Configuration

```toml
# pyproject.toml
[project]
name = "berg-plugin-github"
version = "1.0.0"
description = "GitHub integration for Berg Agents"
authors = [
    {name = "Berg Agents Team", email = "team@berg-agents.dev"}
]
license = {text = "AGPL-3.0-only"}
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.27.0",
    "berg-agents>=0.5.0"]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0"]

[project.entry-points."berg_plugins"]
github = "github_plugin:GitHubPlugin"

[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

## Summary

This example demonstrates:

1. **Complete manifest** with all options
2. **Pydantic settings** with validation
3. **Tool schemas** for type safety
4. **Async tool implementations**
5. **Full plugin class** with lifecycle hooks
6. **Event integration** for communication
7. **Unit tests** with pytest
8. **Package configuration** with entry points

The plugin follows berg_agents patterns:
- Deferred loading for tools
- Risk-based permissions
- Configuration validation
- Event-driven communication
- Graceful error handling