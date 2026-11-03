# Plugin System Requirements & Interface Contracts

*Generated: 2026-10-10*

## Goals

Create a unified, extensible plugin system for berg_agents that:

1. **Preserves existing strengths** - deferred loading, resilient failures, config-driven design
2. **Adds missing capabilities** - lifecycle management, dependencies, versioning, events
3. **Maintains backward compatibility** - existing skills, MCP servers, web backends continue working
4. **Enables rich ecosystem** - third-party plugins, plugin marketplace potential
5. **Stays lean** - plugins remain lightweight with minimal overhead

## Core Requirements

### 1. Plugin Types

Support multiple plugin categories with unified interface:

- **Tool Plugins** - Add new tools/capabilities to agents
- **Agent Plugins** - Custom agent implementations
- **Provider Plugins** - New LLM providers or model sources
- **Backend Plugins** - Web search, memory, storage backends
- **UI Plugins** - Dashboard widgets, visualizations
- **Middleware Plugins** - Request/response transformers
- **Hook Plugins** - Lifecycle event handlers

### 2. Plugin Lifecycle

**States:**
- `discovered` - Found but not loaded
- `loaded` - Manifest parsed, code imported
- `enabled` - Active and available
- `disabled` - Present but inactive
- `error` - Failed to load or crashed

**Transitions:**

```
discovered → loaded → enabled ⟷ disabled
     ↓          ↓         ↓
   error    error     error
```

**Hooks:**
- `on_discover()` - Plugin found
- `on_load()` - Import and validate
- `on_enable()` - Activate plugin
- `on_disable()` - Deactivate plugin
- `on_unload()` - Clean up resources
- `on_error(error)` - Handle failures

### 3. Plugin Manifest

Required fields:
- `id` - Unique identifier (e.g., `berg-plugin-github`)
- `version` - Semantic version (e.g., `1.2.3`)
- `name` - Human-readable name
- `description` - Brief description
- `entry_point` - Python module path (e.g., `berg_plugins.github:GithubPlugin`)

Optional fields:
- `author` - Plugin author
- `license` - License identifier (SPDX)
- `homepage` - Project URL
- `repository` - Source code URL
- `tags` - Category tags
- `icon` - Plugin icon (emoji or URL)
- `dependencies` - Plugin dependencies
- `python_requires` - Python version constraint
- `berg_agents_requires` - Berg agents version constraint
- `settings_schema` - JSON schema for settings
- `permissions` - Required permissions
- `deferred` - Enable deferred loading (default: true)
- `auto_enable` - Enable on load (default: false)

### 4. [Plugin Interface Contract](../lifecycle/bergplugin.py)

All plugins implement a base interface:

```python
from abc import ABC, abstractmethod
from typing import Any


class BergPlugin(ABC):
    """Base interface for all berg_agents plugins."""

    @abstractmethod
    async def on_load(self, context: PluginContext) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context: PluginContext) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context: PluginContext) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context: PluginContext) -> None:
        """Called when plugin is unloaded."""

    def get_capabilities(self) -> list[PluginCapability]:
        """Return plugin capabilities (tools, agents, etc.)."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return JSON schema for plugin settings."""
        return None
```

### 5. [Plugin Context](../plugin_contract.py)

Plugins receive a context object with access to:

```python
class PluginContext:
    """Runtime context provided to plugins."""

    # Plugin metadata
    plugin_id: str
    plugin_version: str
    plugin_dir: Path

    # Berg agents access
    app: BergAgentsApp
    harness: Harness
    config: dict[str, Any]

    # Plugin system
    plugin_manager: PluginManager
    event_bus: EventBus
    logger: logging.Logger

    # Settings
    settings: dict[str, Any]  # Plugin-specific settings

    # Methods
    def emit_event(self, event: str, data: Any) -> None: ...
    def subscribe(self, event: str, handler: Callable) -> None: ...
    def get_plugin(self, plugin_id: str) -> BergPlugin | None: ...
    def register_tool(self, tool: Tool) -> None: ...
    def register_agent(self, agent: AbstractAgent) -> None: ...
```

### 6. [Capability Types](../plugin_contract.py)

Plugins expose capabilities through typed interfaces:

```python
class PluginCapability(ABC):
    """Base for plugin-provided capabilities."""

    type: str


class ToolCapability(PluginCapability):
    type = "tool"
    tool: Tool
    risk_level: RiskClass
    deferred: bool = True


class AgentCapability(PluginCapability):
    type = "agent"
    agent_class: type[AbstractAgent]
    complexity_level: TaskComplexity


class ProviderCapability(PluginCapability):
    type = "provider"
    provider_id: str
    models: dict[str, dict[str, Any]]


class BackendCapability(PluginCapability):
    type = "backend"
    backend_type: str  # "search", "memory", "storage"
    backend_class: type
```

### 7. Dependency Resolution

Plugins declare dependencies with version constraints:

```yaml
dependencies:
  - id: berg-plugin-github
    version: "^1.0.0"
    optional: false
  - id: berg-plugin-jira
    version: ">=2.1.0"
    optional: true
```

**Resolution rules:**
- Semantic versioning (npm/cargo style)
- Dependency graph validation
- Circular dependency detection
- Optional dependencies may be missing
- Load order respects dependencies

### 8. Security & Permissions

Plugins declare required permissions:

```yaml
permissions:
  - filesystem:read
  - filesystem:write
  - network:outbound
  - env:read
  - subprocess:spawn
```

**Permission levels:**
- `filesystem:read` - Read files
- `filesystem:write` - Write/modify files
- `network:outbound` - Make HTTP requests
- `network:inbound` - Listen on ports
- `env:read` - Read environment variables
- `env:write` - Modify environment
- `subprocess:spawn` - Execute commands
- `system:admin` - Administrative access

**Enforcement:**
- Permissions checked at runtime
- User prompted for approval (HITL)
- Denied permissions → graceful degradation
- Audit log of permission usage

### 9. Configuration

Plugins get isolated configuration:

```yaml
# .berg-agents/plugins/berg-plugin-github.yaml
enabled: true
settings:
  token: ${env:GITHUB_TOKEN}
  org: myorg
  rate_limit: 5000
```

**Config sources (priority order):**
1.
Runtime overrides
2.
User config (`../../../.berg-agents`)
3.
Plugin defaults (`plugin.yaml` in plugin package)
4.
Schema defaults

### 10. Event System

Plugins communicate via typed events:

**System events:**
- `plugin.discovered` - Plugin found
- `plugin.loaded` - Plugin loaded
- `plugin.enabled` - Plugin enabled
- `plugin.disabled` - Plugin disabled
- `plugin.error` - Plugin error
- `agent.task.started` - Task started
- `agent.task.completed` - Task completed
- `agent.tool.called` - Tool invoked

**Custom events:**
- Plugins emit domain-specific events
- Type-safe with Pydantic models
- Subscribe/unsubscribe dynamically

### 11. Discovery Mechanisms

Multiple ways to discover plugins:

1. **Package plugins** - Installed pip packages with `../../../..` entry point
2. **Local plugins** - Directory at `../../../.berg-agents`
3. **Remote plugins** - Git URLs, HTTP archives
4. **Built-in plugins** - Shipped with berg_agents

**Discovery order:**
1.
Built-in (highest priority)
2.
Local directory
3.
Installed packages
4.
Remote (cached locally)

### 12. Deferred Loading (Critical)

Maintain context efficiency:

- **Catalog mode** - Show only `id`, `description`, `version`
- **Full load** - Load complete plugin when needed
- **Lazy import** - Import Python modules only when used
- **Capability deferral** - Large tools/agents load on demand

```python
# Catalog entry (shown to model)
{
    "id": "berg-plugin-github",
    "description": "GitHub integration with issues, PRs, repos",
    "version": "1.2.0"}

# Full plugin loaded via tool call or explicit request
await plugin_manager.load_plugin("berg-plugin-github")
```

### 13. Error Handling & Resilience

Follow existing patterns:

- **Fail gracefully** - One broken plugin doesn't break the system
- **Log warnings** - Failed plugins logged, not raised
- **Partial availability** - Some capabilities may work even if others fail
- **Health checks** - Periodic plugin health validation
- **Auto-recovery** - Attempt to reload failed plugins

### 14. Versioning & Compatibility

- **Semantic versioning** - MAJOR.MINOR.PATCH
- **API version** - Plugin API version separate from berg_agents version
- **Deprecation warnings** - Warn before breaking changes
- **Migration path** - Tools to upgrade plugins
- **Compatibility matrix** - Document version compatibility

### 15. Testing & Validation

Plugins must be testable:

- **Manifest validation** - Schema validation at load
- **Dependency validation** - Check all dependencies present
- **Permission validation** - Ensure permissions are declared
- **Health check** - Verify plugin loads and basic functionality
- **Unit tests** - Plugin authors provide tests
- **Integration tests** - Test plugin with berg_agents

## Non-Functional Requirements

### Performance

- Plugin discovery < 100ms for 100 plugins
- Plugin load < 500ms per plugin
- Deferred loading: catalog < 1KB per plugin
- Event dispatch < 10ms

### Reliability

- One plugin crash doesn't crash system
- Automatic restart on transient failures
- Graceful degradation when plugin unavailable

### Security

- Sandboxing for untrusted plugins (future)
- Permission system enforced
- No direct access to internals
- Audit trail

### Developer Experience

- Simple plugin creation (< 50 lines for basic plugin)
- Rich documentation and examples
- Clear error messages
- Hot reload during development

### Backward Compatibility

- Existing skills continue working
- Existing MCP servers continue working
- Existing web backends continue working
- Migration tools provided

## Success Criteria

1. ✅ Can convert existing skills to plugins
2. ✅ Can convert existing MCP servers to plugins
3. ✅ Can add new plugin without code changes
4. ✅ Plugins can depend on each other
5. ✅ One broken plugin doesn't break system
6. ✅ Deferred loading maintains context efficiency
7. ✅ Permission system prevents unauthorized access
8. ✅ Third-party developers can publish plugins
9. ✅ Plugin development < 1 hour for experienced dev
10. ✅ 100+ plugins load in < 10 seconds

## Next Steps

1. Design plugin discovery and registration mechanism
2. Design plugin lifecycle state machine
3. Design dependency resolution algorithm
4. Design security and permission model
5. Create plugin manifest schema
6. Implement base plugin classes
7. Build example plugins
8. Write migration guide

--------------------------------------------------------------------------------

**Note:** This design preserves berg_agents' strengths (deferred loading, resilience, config-driven) while adding the structure needed for a rich plugin ecosystem.
The key innovation is **unified interface + deferred loading** - plugins are cheap until actually used.
