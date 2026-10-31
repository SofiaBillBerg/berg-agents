# Migration Guide: Converting Existing Capabilities to Plugins

*Generated: 2026-10-10*

## Overview

This guide shows how to migrate existing berg_agents capabilities (Skills, MCP servers, web backends) to the new unified plugin system while maintaining backward compatibility.

## Migration Strategy

### Phase 1: Backward Compatibility (Immediate)

All existing capabilities continue working through **adapter plugins** that wrap the old formats.

### Phase 2: Gradual Migration (Recommended)

Convert capabilities to native plugins over time for better features and performance.

### Phase 3: Deprecation (Future)

Old formats eventually deprecated after migration period.

## Timeline

```
Now (v0.5)        → Phase 1: Adapters active, old formats work
v0.6-0.8          → Phase 2: New plugins recommended, migration tools
v0.9              → Phase 3: Old formats deprecated (warnings)
v1.0              → Phase 4: Old formats removed
```

## Migrating Skills

### Current Skills Format

```
.agents/skills/
└── my-skill/
    └── SKILL.md
```

```markdown
---
name: My Skill
description: Does something useful
---

# Skill Content

Instructions for the agent...
```

### Migration Options

#### Option 1: Keep as Skill (No Changes)

Skills continue working via the built-in `SkillPluginAdapter`:

```python
# Built-in adapter (automatic)
class SkillPluginAdapter(BergPlugin):
    """Wraps existing skills as plugins."""

    # Automatically applied to all .agents/skills/
```

**No action needed** - your skills work as-is.

#### Option 2: Convert to Native Plugin

Create a proper plugin for better features:

```yaml
# plugin.yaml
id: berg-plugin-my-skill
version: 1.0.0
name: My Skill
description: Does something useful

entry_point: my_skill:MySkillPlugin

capabilities:
  - type: skill
    id: my-skill
    name: My Skill
    content_file: skill.md
    deferred: true
```

```python
# my_skill.py
from berg_agents.plugins import BergPlugin, PluginContext
from pathlib import Path


class MySkillPlugin(BergPlugin):
    """Native skill plugin."""

    def __init__(self):
        self.content = None

    async def on_load(self, context: PluginContext) -> None:
        """Load skill content."""
        skill_file = Path(__file__).parent / "skill.md"
        self.content = skill_file.read_text()

    def get_capabilities(self) -> list:
        from berg_agents.plugins.capabilities import SkillCapability

        return [
            SkillCapability(
                type="skill",
                id="my-skill",
                name="My Skill",
                description="Does something useful",
                content=self.content,
                deferred=True,
            )
        ]
```

**Benefits:**
- Version management
- Dependencies
- Configuration
- Events
- Better lifecycle control

#### Option 3: Auto-Migration Tool

```bash
# Auto-convert skill to plugin
$ berg-agents plugin migrate skill \
    --input .agents/skills/my-skill/SKILL.md \
    --output .berg-agents/plugins/berg-plugin-my-skill/

# Result:
# .berg-agents/plugins/berg-plugin-my-skill/
# ├── plugin.yaml
# ├── __init__.py
# ├── skill_plugin.py
# └── skill.md
```

### Migration Steps

1. **Audit existing skills**
   ```bash
   $ berg-agents skills list
   ```

2. **Choose migration approach**
   - Keep as-is (adapter)
   - Convert critical skills to plugins
   - Use auto-migration tool

3. **Test after migration**
   ```bash
   $ berg-agents plugin validate .berg-agents/plugins/berg-plugin-my-skill/
   ```

4. **Update documentation**

## Migrating MCP Servers

### Current MCP Format

```json
// .berg-agents /mcp.json
{
  "mcpServers": {
    "github": {
      "type": "remote",
      "url": "https://mcp.github.com",
      "enabled": true
    }
  }
}
```

### Migration Options

#### Option 1: Keep as MCP Server (No Changes)

MCP servers continue working via `MCPPluginAdapter`:

```python
# Built-in adapter (automatic)
class MCPPluginAdapter(BergPlugin):
    """Wraps MCP servers as plugins."""

    # Automatically applied to all .berg-agents /mcp.json entries
```

**No action needed** - your MCP servers work as-is.

#### Option 2: Convert to Native Plugin

Wrap MCP server in a plugin for better control:

```yaml
# plugin.yaml
id: berg-plugin-github-mcp
version: 1.0.0
name: GitHub MCP Integration
description: GitHub tools via MCP

entry_point: github_mcp:GitHubMCPPlugin

requirements:
  berg_agents: ">=0.5.0"

settings_schema:
  type: object
  properties:
    server_url:
      type: string
      default: "https://mcp.github.com"
    token:
      type: string
      secret: true

permissions:
  - network:outbound:
      domains:
        - "mcp.github.com"
        - "api.github.com"
```

```python
# github_mcp.py
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.core.mcp import create_mcp_client


class GitHubMCPPlugin(BergPlugin):
    """GitHub MCP as a plugin."""

    def __init__(self):
        self.mcp_client = None
        self.tools = []

    async def on_load(self, context: PluginContext) -> None:
        """Connect to MCP server."""
        server_url = context.get_setting("server_url")
        token = context.get_setting("token")

        self.mcp_client = await create_mcp_client(url=server_url, token=token)

        # List available tools
        self.tools = await self.mcp_client.list_tools()

    async def on_disable(self, context: PluginContext) -> None:
        """Disconnect from MCP server."""
        if self.mcp_client:
            await self.mcp_client.close()

    def get_capabilities(self) -> list:
        from berg_agents.plugins.capabilities import MCPCapability

        return [
            MCPCapability(
                type="mcp", server_url=self.mcp_client.url, tools=self.tools
            )
        ]
```

#### Option 3: Auto-Migration

```bash
# Auto-convert MCP server to plugin
$ berg-agents plugin migrate mcp \
    --server github \
    --input .berg-agents /mcp.json \
    --output .berg-agents/plugins/berg-plugin-github-mcp/
```

### Migration Steps

1. **List MCP servers**
   ```bash
   $ berg-agents mcp list
   ```

2. **Test current setup**
   ```bash
   $ berg-agents mcp test github
   ```

3. **Migrate critical servers**
   ```bash
   $ berg-agents plugin migrate mcp --server github
   ```

4. **Verify after migration**
   ```bash
   $ berg-agents plugin show berg-plugin-github-mcp
   ```

## Migrating Web Backends

### Current Web Backend Format

```python
# berg_agents/capabilities/web_backends.py
class SearchBackend(ABC):
    @abstractmethod
    async def search(self, query: str) -> list[dict]:
        pass


class MyCustomBackend(SearchBackend):
    async def search(self, query: str) -> list[dict]:
        # Implementation
        pass
```

### Migration to Plugin

```yaml
# plugin.yaml
id: berg-plugin-my-search
version: 1.0.0
name: My Search Backend
description: Custom search backend

entry_point: my_search:MySearchPlugin

capabilities:
  - type: backend
    backend_type: search
    name: My Search

permissions:
  - network:outbound
```

```python
# my_search.py
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import BackendCapability


class MySearchBackend:
    """Search backend implementation."""

    async def search(self, query: str) -> list[dict]:
        # Implementation
        return []


class MySearchPlugin(BergPlugin):
    """Search backend plugin."""

    def __init__(self):
        self.backend = None

    async def on_load(self, context: PluginContext) -> None:
        """Initialize backend."""
        self.backend = MySearchBackend()

    def get_capabilities(self) -> list:
        return [
            BackendCapability(
                type="backend",
                backend_type="search",
                backend_instance=self.backend,
            )
        ]
```

### Migration Steps

1. **Identify custom backends**
   ```bash
   $ grep -r "class.*Backend" berg_agents/capabilities/
   ```

2. **Extract to plugin**
   - Copy backend implementation
   - Create plugin wrapper
   - Update manifest

3. **Test backend**
   ```python
   # test_backend.py
   plugin = MySearchPlugin()
   await plugin.on_load(mock_context)
   
   caps = plugin.get_capabilities()
   backend = caps[0].backend_instance
   
   results = await backend.search("test query")
   assert len(results) > 0
   ```

## Migrating Custom Tools

### Current Tool Format

```python
# berg_agents/agents/workspace_toolset.py
async def my_custom_tool(arg1: str, arg2: int) -> str:
    """My custom tool."""
    return "result"


# Registered manually in agent
```

### Migration to Plugin

```yaml
# plugin.yaml
id: berg-plugin-my-tools
version: 1.0.0
name: My Custom Tools
description: Collection of custom tools

entry_point: my_tools:MyToolsPlugin

capabilities:
  - type: tool
    id: my-custom-tool
    name: My Custom Tool
    risk_level: medium
    deferred: true
```

```python
# my_tools.py
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import ToolCapability
from pydantic import BaseModel


class MyToolInput(BaseModel):
    arg1: str
    arg2: int


class MyToolOutput(BaseModel):
    result: str


async def my_custom_tool(input_data: MyToolInput) -> MyToolOutput:
    """My custom tool."""
    # Implementation
    return MyToolOutput(result="done")


class MyToolsPlugin(BergPlugin):
    """Custom tools plugin."""

    def get_capabilities(self) -> list:
        return [
            ToolCapability(
                type="tool",
                tool=my_custom_tool,
                risk_level="medium",
                deferred=True,
            )
        ]
```

### Migration Steps

1. **Extract tool functions**
   - Copy to separate module
   - Add Pydantic schemas
   - Add proper typing

2. **Create plugin wrapper**
   - Write manifest
   - Implement plugin class
   - Register tools as capabilities

3. **Update tool calls**
   - Tools now called through plugin system
   - No code changes in agents (automatic)

## Migrating Custom Agents

### Current Agent Format

```python
# berg_agents/agents/my_agent.py
class MyCustomAgent(AbstractAgent):
    async def run(self, context: TaskContext) -> AgentResult:
        # Implementation
        pass
```

### Migration to Plugin

```yaml
# plugin.yaml
id: berg-plugin-my-agent
version: 1.0.0
name: My Custom Agent
description: Custom agent implementation

entry_point: my_agent:MyAgentPlugin

capabilities:
  - type: agent
    id: my-custom-agent
    name: My Custom Agent
    complexity: medium
```

```python
# my_agent.py
from berg_agents.plugins import BergPlugin, PluginContext
from berg_agents.plugins.capabilities import AgentCapability
from berg_agents.core import AbstractAgent, AgentResult, TaskContext


class MyCustomAgent(AbstractAgent):
    """Custom agent implementation."""

    async def run(self, context: TaskContext) -> AgentResult:
        # Implementation
        return AgentResult(success=True)


class MyAgentPlugin(BergPlugin):
    """Custom agent plugin."""

    def get_capabilities(self) -> list:
        return [
            AgentCapability(
                type="agent", agent_class=MyCustomAgent, complexity="medium"
            )
        ]
```

## Migration Checklist

### Pre-Migration

- [ ] Audit all current capabilities
- [ ] Document current functionality
- [ ] Create test coverage
- [ ] Backup configuration files

### During Migration

- [ ] Choose migration approach (adapter vs. native)
- [ ] Create plugin manifest
- [ ] Implement plugin class
- [ ] Add tests
- [ ] Update documentation

### Post-Migration

- [ ] Test thoroughly
- [ ] Verify all features work
- [ ] Update configuration
- [ ] Monitor for issues
- [ ] Clean up old files (optional)

## Testing After Migration

```python
# test_migration.py
import pytest
from my_plugin import MyPlugin


@pytest.mark.asyncio
async def test_migrated_functionality():
    """Test that migrated plugin works like original."""
    plugin = MyPlugin()

    # Load
    await plugin.on_load(mock_context)

    # Enable
    await plugin.on_enable(mock_context)

    # Test capabilities
    caps = plugin.get_capabilities()
    assert len(caps) > 0

    # Test each capability
    for cap in caps:
        # Verify capability works
        pass

    # Clean up
    await plugin.on_disable(mock_context)
```

## Rollback Plan

If migration causes issues:

### 1. Disable New Plugin

```bash
$ berg-agents plugin disable berg-plugin-my-new-plugin
```

### 2. Restore Old Configuration

```bash
# Restore from backup
$ cp .berg-agents /mcp.json.backup .berg-agents /mcp.json
$ cp -r .agents/skills.backup .agents/skills
```

### 3. Restart Berg Agents

```bash
$ berg-agents restart
```

## Common Issues

### Issue: Plugin Not Loading

**Cause:** Invalid manifest or missing dependencies

**Solution:**
```bash
$ berg-agents plugin validate plugin.yaml
$ pip install -e .
```

### Issue: Tools Not Appearing

**Cause:** Capabilities not registered properly

**Solution:**
```python
def get_capabilities(self) -> list:
    # Ensure returning list of capabilities
    return [ToolCapability(...)]
```

### Issue: Configuration Errors

**Cause:** Settings schema mismatch

**Solution:**
```bash
$ berg-agents config validate berg-plugin-name
```

### Issue: Permission Denied

**Cause:** Missing permissions in manifest

**Solution:**
```yaml
# Add to plugin.yaml
permissions:
  - network:outbound
  - filesystem:read
```

## Migration Tools Reference

```bash
# List all capabilities
$ berg-agents capabilities list

# Migrate skill to plugin
$ berg-agents plugin migrate skill --input path/to/SKILL.md

# Migrate MCP server to plugin
$ berg-agents plugin migrate mcp --server name

# Validate migrated plugin
$ berg-agents plugin validate path/to/plugin/

# Test migrated plugin
$ berg-agents plugin test plugin-id

# Compare old vs. new
$ berg-agents plugin compare old-capability new-plugin-id
```

## Best Practices

1. **Migrate incrementally** - One capability at a time
2. **Test thoroughly** - Ensure nothing breaks
3. **Keep backups** - Easy rollback if needed
4. **Document changes** - Update docs and comments
5. **Monitor after migration** - Watch for issues
6. **Use adapters initially** - Native plugins later
7. **Leverage auto-migration** - Tools do heavy lifting

## Benefits of Migration

### Before (Old Format)

- Scattered configuration
- No version management
- No dependencies
- Limited lifecycle control
- No inter-capability communication

### After (Plugin System)

- Unified configuration
- Semantic versioning
- Dependency resolution
- Full lifecycle hooks
- Event-driven communication
- Better testing
- Marketplace support

## Getting Help

If you encounter issues during migration:

1. **Check migration guide** (this document)
2. **Use validation tools** (`berg-agents plugin validate`)
3. **Review examples** (see example plugin)
4. **Ask community** (Discord, GitHub Discussions)
5. **File issue** if you find bugs

## Summary

Migration path:
1. **Keep using old format** (adapters work automatically)
2. **Migrate critical capabilities** to plugins when ready
3. **Use auto-migration tools** to save time
4. **Test thoroughly** before and after
5. **Monitor and rollback** if needed

The plugin system is designed for **gradual adoption** - you don't need to migrate everything at once. Start with new features as plugins, migrate existing capabilities over time.

---

Good luck with your migration! 🚀
