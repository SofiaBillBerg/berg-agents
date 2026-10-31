# Plugin Development Guide

*Generated: 2026-10-10*

## Overview

This guide walks through creating a berg_agents plugin from scratch, covering setup, development, testing, debugging, and publishing.

## Prerequisites

- Python 3.10 or higher
- Berg agents 0.5.0 or higher
- Basic familiarity with async Python
- Git (for version control)

## Quick Start

### 1. Create Plugin Scaffold

```bash
# Use CLI to create plugin template
$ berg-agents plugin create my-awesome-plugin

# Or manually create structure
$ mkdir berg-plugin-my-awesome
$ cd berg-plugin-my-awesome
$ touch plugin.yaml __init__.py my_plugin.py
```

### 2. Define Manifest

```yaml
# plugin.yaml
id: berg-plugin-my-awesome
version: 0.1.0
name: My Awesome Plugin
description: Does awesome things

author:
  name: Your Name
  email: you@example.com

license: GNU Affero General Public License

entry_point: my_plugin:MyAwesomePlugin

requirements:
  python: ">=3.10"
  berg_agents: ">=0.5.0"

settings_schema:
  type: object
  properties:
    api_key:
      type: string
      secret: true
      description: API key for awesome service

permissions:
  - network:outbound
```

### 3. Implement Plugin

```python
# my_plugin.py
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import ToolCapability
from pydantic import BaseModel, SecretStr


class MyAwesomeSettings(BaseModel):
    api_key: SecretStr


class MyAwesomePlugin(BergPlugin):
    """My awesome plugin."""

    def __init__(self):
        self.settings: MyAwesomeSettings | None = None

    async def on_load(self, context: PluginContext) -> None:
        """Load plugin."""
        self.settings = MyAwesomeSettings(**context.settings)
        print(f"Loaded {context.plugin_id}")

    async def on_enable(self, context: PluginContext) -> None:
        """Enable plugin."""
        print(f"Enabled {context.plugin_id}")

    def get_capabilities(self) -> list[ToolCapability]:
        """Return capabilities."""
        return []
```

### 4. Test Locally

```bash
# Install in development mode
$ pip install -e .

# Or place in .berg-agents/plugins/ directory
$ mkdir -p .berg-agents/plugins/
$ ln -s $(pwd) .berg-agents/plugins/berg-plugin-my-awesome

# Start berg-agents
$ berg-agents --web
```

## Development Workflow

### Step 1: Design Your Plugin

Answer these questions:

1. **What problem does it solve?**
   - Define clear use case
   - Identify target users

2. **What capabilities does it provide?**
   - Tools (functions agents can call)
   - Agents (custom agent implementations)
   - Providers (LLM backends)
   - Backends (search, storage, etc.)

3. **What dependencies does it need?**
   - Python packages
   - Other plugins
   - System commands

4. **What permissions does it require?**
   - Filesystem access
   - Network access
   - Environment variables

### Step 2: Create Project Structure

```
berg-plugin-myname/
├── plugin.yaml              # Manifest (required)
├── README.md                # Documentation
├── LICENSE                  # License file
├── pyproject.toml          # Python package config
├── __init__.py             # Package init
├── plugin.py               # Main plugin class
├── config.py               # Settings model
├── tools.py                # Tool implementations
├── schemas.py              # Pydantic schemas
├── client.py               # API client (if needed)
├── tests/
│   ├── __init__.py
│   ├── test_plugin.py
│   ├── test_tools.py
│   └── fixtures/
└── docs/
    └── usage.md
```

### Step 3: Implement Core Functionality

#### Settings Model

```python
# config.py
from pydantic import BaseModel, Field, SecretStr


class MyPluginSettings(BaseModel):
    """Plugin configuration."""

    api_key: SecretStr = Field(..., description="API key")
    base_url: str = Field(
        default="https://api.example.com", description="API base URL"
    )
    timeout: int = Field(
        default=30, ge=1, le=300, description="Request timeout in seconds"
    )
```

#### Tool Schemas

```python
# schemas.py
from pydantic import BaseModel, Field


class CreateThingInput(BaseModel):
    """Input for creating a thing."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")


class CreateThingOutput(BaseModel):
    """Output from creating a thing."""

    id: str
    url: str
```

#### Tool Implementation

```python
# tools.py
import httpx
import logging
from .config import MyPluginSettings
from .schemas import CreateThingInput, CreateThingOutput

logger = logging.getLogger(__name__)


async def create_thing(
    settings: MyPluginSettings, input_data: CreateThingInput
) -> CreateThingOutput:
    """Create a thing via API."""
    async with httpx.AsyncClient(
        base_url=settings.base_url,
        headers={
            "Authorization": f"Bearer {settings.api_key.get_secret_value()}"
        },
        timeout=settings.timeout,
    ) as client:
        response = await client.post(
            "/things",
            json={
                "name": input_data.name,
                "description": input_data.description},
        )
        response.raise_for_status()
        data = response.json()

        return CreateThingOutput(id=data["id"], url=data["url"])
```

#### [Plugin Class](plugin.py)

```python
# plugin.py
import logging
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import ToolCapability
from berg_agents.plugins.health import HealthStatus
from .config import MyPluginSettings
from .tools import create_thing

logger = logging.getLogger(__name__)


class MyPlugin(BergPlugin):
    """My plugin implementation."""

    def __init__(self):
        self.settings: MyPluginSettings | None = None

    # === Lifecycle Hooks ===

    async def on_load(self, context: PluginContext) -> None:
        """Load plugin."""
        logger.info(f"Loading {context.plugin_id}")

        # Parse settings
        self.settings = MyPluginSettings(**context.settings)

        # Initialize client, connections, etc.
        logger.info("Plugin loaded successfully")

    async def on_enable(self, context: PluginContext) -> None:
        """Enable plugin."""
        logger.info(f"Enabling {context.plugin_id}")

        # Subscribe to events
        self.subscribe("agent.task.*", self._on_agent_event)

        # Start background tasks if needed

        # Emit enabled event
        await self.emit("plugin.myplugin.enabled", {})

    async def on_disable(self, context: PluginContext) -> None:
        """Disable plugin."""
        logger.info(f"Disabling {context.plugin_id}")

        # Stop background tasks
        # Close connections

    async def on_unload(self, context: PluginContext) -> None:
        """Unload plugin."""
        logger.info(f"Unloading {context.plugin_id}")

        # Final cleanup

    async def on_error(self, context: PluginContext, error: Exception) -> None:
        """Handle errors."""
        logger.error(f"Plugin error: {error}", exc_info=True)
        await self.emit("plugin.myplugin.error", {"error": str(error)})

    # === Configuration ===

    async def on_config_change(
        self, context: PluginContext, new_config: dict
    ) -> None:
        """Handle configuration changes."""
        logger.info("Configuration changed")

        # Re-parse settings
        old_settings = self.settings
        self.settings = MyPluginSettings(**new_config)

        # Restart connections if needed
        if old_settings.base_url != self.settings.base_url:
            # Reconnect with new URL
            pass

    # === Capabilities ===

    def get_capabilities(self) -> list[ToolCapability]:
        """Return plugin capabilities."""
        return [
            ToolCapability(
                type="tool",
                tool=create_thing,
                risk_level="medium",
                deferred=True,
            )]

    def get_settings_schema(self) -> dict | None:
        """Return settings schema."""
        return MyPluginSettings.model_json_schema()

    # === Health Check ===

    async def health_check(self, context: PluginContext) -> HealthStatus:
        """Check plugin health."""
        try:
            # Ping API or check connections
            return HealthStatus(status="healthy")
        except Exception as e:
            return HealthStatus(status="degraded", message=str(e))

    # === Event Handlers ===

    async def _on_agent_event(self, event) -> None:
        """Handle agent events."""
        logger.debug(f"Agent event: {event.type}")
        # React to agent events
```

### Step 4: Write Tests

```python
# tests/test_plugin.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from plugin import MyPlugin
from config import MyPluginSettings


@pytest.fixture
def mock_context():
    """Create mock plugin context."""
    context = MagicMock()
    context.plugin_id = "berg-plugin-myplugin"
    context.plugin_version = "0.1.0"
    context.settings = {
        "api_key": "test-key",
        "base_url": "https://api.test.com",
        "timeout": 30}
    context.event_bus = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_plugin_loads(mock_context):
    """Test plugin loads successfully."""
    plugin = MyPlugin()
    await plugin.on_load(mock_context)

    assert plugin.settings is not None
    assert plugin.settings.base_url == "https://api.test.com"


@pytest.mark.asyncio
async def test_plugin_enables(mock_context):
    """Test plugin enables."""
    plugin = MyPlugin()
    await plugin.on_load(mock_context)
    await plugin.on_enable(mock_context)

    # Check event emitted
    assert mock_context.event_bus.emit.called


# Run tests
# $ pytest tests/ -v
```

### Step 5: Add Documentation

```markdown
# README.md

# My Awesome Plugin

Description of what your plugin does.

## Installation

```bash
pip install berg-plugin-myawesome
```

## Configuration

```yaml
# .berg-agents/plugins/berg-plugin-myawesome.yaml
enabled: true
settings:
  api_key: ${env:MY_API_KEY}
  timeout: 30
```

## Usage

### Create a Thing

```python
result = await create_thing(name="My Thing", description="A cool thing")
print(result.url)
```

## License

AGPL
```

## Debugging Tips

### Enable Debug Logging

```python
# In your plugin
import logging
logging.getLogger(__name__).setLevel(logging.DEBUG)
```

```yaml
# .berg-agents/bergagents.yaml
logging:
  level: DEBUG
  plugins:
    berg-plugin-myawesome: DEBUG
```

### Use Breakpoints

```python
# Add breakpoint in plugin code
async def on_load(self, context: PluginContext) -> None:
    breakpoint()  # Debugger will stop here
    self.settings = MyPluginSettings(**context.settings)
```

### Test in Isolation

```python
# test_isolated.py
import asyncio
from plugin import MyPlugin
from unittest.mock import MagicMock


async def main():
    plugin = MyPlugin()

    # Create minimal context
    context = MagicMock()
    context.settings = {"api_key": "test"}

    # Test lifecycle
    await plugin.on_load(context)
    await plugin.on_enable(context)

    # Test capabilities
    caps = plugin.get_capabilities()
    print(f"Capabilities: {caps}")

    # Clean up
    await plugin.on_disable(context)
    await plugin.on_unload(context)


asyncio.run(main())
```

### Hot Reload During Development

```bash
# Watch for changes and auto-reload
$ berg-agents --web --dev --reload
```

## Publishing Your Plugin

### 1. Prepare for Release

```bash
# Run tests
$ pytest tests/ -v --cov

# Check code quality
$ ruff check .
$ mypy .

# Build package
$ python -m build
```

### 2. Publish to PyPI

```bash
# Test on PyPI test server first
$ twine upload --repository testpypi dist/*

# Publish to PyPI
$ twine upload dist/*
```

### 3. Submit to Plugin Registry

```bash
# Submit to official berg-agents plugin registry
$ berg-agents plugin submit \
    --name berg-plugin-myawesome \
    --version 1.0.0 \
    --repo https://github.com/you/berg-plugin-myawesome
```

## Best Practices

### 1. Error Handling

```python
# Always handle errors gracefully
async def on_enable(self, context: PluginContext) -> None:
    try:
        # Initialize
        pass
    except Exception as e:
        logger.error(f"Failed to enable: {e}")
        # Don't raise - let plugin system handle it
```

### 2. Resource Cleanup

```python
# Always clean up resources
async def on_disable(self, context: PluginContext) -> None:
    if self.client:
        await self.client.close()
        self.client = None
```

### 3. Async Best Practices

```python
# Use async context managers
async with httpx.AsyncClient() as client:
    response = await client.get("/data")

# Avoid blocking calls
# BAD:
time.sleep(10)

# GOOD:
await asyncio.sleep(10)
```

### 4. Configuration Validation

```python
# Validate settings early
class Settings(BaseModel):
    url: str
    
    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("URL must use HTTPS")
        return v
```

### 5. Deferred Loading

```python
# Mark expensive capabilities as deferred
ToolCapability(
    type="tool",
    tool=expensive_operation,
    deferred=True,  # Load only when called
)
```

### 6. Security

```python
# Never log secrets
logger.info(f"API key: {settings.api_key.get_secret_value()}")  # BAD

logger.info("API key configured")  # GOOD


# Validate all inputs
class Input(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        # Prevent path traversal
        if ".." in v:
            raise ValueError("Invalid path")
        return v
```

### 7. Event Communication

```python
# Emit events for important actions
await self.emit(
    "plugin.myname.action.completed", {"action_id": action_id, "result": result}
)

# Subscribe to relevant events
self.subscribe("agent.task.*", self._on_task)
```

## Troubleshooting

### Plugin Not Loading

1. Check manifest syntax: `berg-agents plugin validate plugin.yaml`
2. Check entry point exists
3. Check dependencies are installed
4. Check Python version compatibility

### Tools Not Appearing

1. Ensure plugin is enabled
2. Check `get_capabilities()` returns tools
3. Check tool schemas are valid
4. Enable debug logging

### Permission Denied

1. Check required permissions in manifest
2. Grant permissions via CLI or config
3. Check permission scopes match usage

### Import Errors

1. Install plugin in development mode: `pip install -e .`
2. Check `../../../pyproject.toml` dependencies
3. Ensure Python path includes plugin directory

## Resources

- [Example Plugin](10-example-plugin.md)
- [Manifest Schema](09-plugin-manifest-schema.md)
- [API Reference](https://berg-agents.dev/api)
- [Plugin Registry](https://plugins.berg-agents.dev)

## Getting Help

- GitHub Discussions: https://github.com/berg-agents/berg-agents/discussions
- Discord: https://discord.gg/berg-agents
- Email: support@berg-agents.dev

## Next Steps

1. Build your plugin following this guide
2. Test thoroughly with unit and integration tests
3. Document usage clearly
4. Publish to PyPI
5. Submit to plugin registry
6. Share with the community!

---

Happy plugin development! 🚀
