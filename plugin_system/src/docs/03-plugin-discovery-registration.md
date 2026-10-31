# Plugin Discovery & Registration Mechanism

*Generated: 2026-10-10*

## Overview

The plugin discovery system finds, validates, and registers plugins from multiple sources while maintaining backward compatibility with existing berg_agents capabilities (Skills, MCP servers, web backends).

## Discovery Sources

### 1. Built-in Plugins

**Location:** `berg_agents/plugins/builtin/`

**Purpose:** Core plugins shipped with berg_agents

**Discovery:**
- Scanned at startup
- Always available
- Highest priority (cannot be overridden)

**Structure:**
```
berg_agents/plugins/builtin/
├── skills/              # Existing skills as plugins
├── mcp/                 # MCP integration plugin
├── web_backends/        # Web search/fetch plugin
└── workspace/           # Workspace tools plugin
```

**Advantages:**
- No installation needed
- Guaranteed availability
- Version matched to berg_agents

### 2. Installed Package Plugins

**Location:** Python packages with `../../../..` entry point

**Discovery:**
```toml
# setup.py or pyproject.toml
[project.entry-points."berg_plugins"]
github = "berg_plugins.github:GithubPlugin"
jira = "berg_plugins.jira:JiraPlugin"
```

[**Discovery mechanism:**](../discovery/discovery_process.py)

```python
from importlib.metadata import entry_points


def discover_package_plugins() -> list[PluginMetadata]:
    """Discover plugins from installed packages."""
    discovered = []
    for ep in entry_points(group="berg_plugins"):
        try:
            plugin_class = ep.load()
            metadata = extract_metadata(plugin_class)
            discovered.append(metadata)
        except Exception as e:
            logger.warning(f"Failed to load plugin {ep.name}: {e}")
    return discovered
```

**Advantages:**
- Standard Python packaging
- Dependency management via pip/uv
- Version pinning
- Easy distribution (PyPI)

**Naming convention:** `berg-plugin-<name>`

### 3. Local Directory Plugins

**Location:** `../../../.berg-agents`

**Structure:**
```
.berg-agents/plugins/
├── my-custom-plugin/
│   ├── plugin.yaml      # Manifest
│   ├── __init__.py      # Entry point
│   └── tools.py         # Implementation
└── another-plugin/
    ├── plugin.yaml
    └── __init__.py
```

[**Discovery:**](../discovery/discovery_process.py)

```python
def discover_local_plugins(plugin_dir: Path) -> list[PluginMetadata]:
    """Discover plugins from local directory."""
    discovered = []
    for item in plugin_dir.iterdir():
        if not item.is_dir():
            continue
        manifest_path = item / "plugin.yaml"
        if manifest_path.exists():
            try:
                metadata = parse_manifest(manifest_path)
                discovered.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to parse {manifest_path}: {e}")
    return discovered
```

**Advantages:**
- No packaging needed
- Fast development iteration
- Project-specific plugins
- Easy hot reload

**Use cases:**
- Development and testing
- Organization-internal plugins
- Quick prototypes

### 4. Remote Plugins (Future)

**Location:** Git repositories, HTTP archives

**Examples:**
```yaml
# .berg-agents/plugins.yaml
remote_plugins:
  - url: "git+https://github.com/org/plugin.git"
    ref: "v1.0.0"
  - url: "https://example.com/plugins/myplugin.tar.gz"
    checksum: "sha256:..."
```

**Discovery:**
- Download to cache directory
- Verify checksums
- Extract and validate
- Add to local plugin path

**Security:**
- Checksum verification required
- Signature verification (future)
- Sandboxing (future)

**Not implemented in v1** - include in future roadmap

## Discovery Process

### Startup Sequence

```
1. Initialize PluginManager
   ↓
2. Discover from all sources (parallel)
   ├── Built-in plugins
   ├── Installed packages
   └── Local directory
   ↓
3. Deduplicate by plugin_id (priority: builtin > local > package)
   ↓
4. Parse manifests and validate
   ↓
5. Build dependency graph
   ↓
6. Detect circular dependencies
   ↓
7. Topological sort (load order)
   ↓
8. Create plugin registry
   ↓
9. Load enabled plugins (async)
   ↓
10. Register capabilities
```

### [Discovery Algorithm](../discovery/discovery_process.py)

```python
class PluginDiscovery:
    """Plugin discovery coordinator."""

    def __init__(self, config: dict[str, Any]):
        self.plugin_dir = Path(config.get("plugin_dir", ".berg-agents/plugins"))
        self.cache_dir = Path(config.get("cache_dir", ".cache/plugins"))

    async def discover_all(self) -> list[PluginMetadata]:
        """Discover plugins from all sources."""
        results = await asyncio.gather(
            self._discover_builtin(),
            self._discover_packages(),
            self._discover_local(),
            return_exceptions=True,
        )

        # Flatten and filter errors
        discovered = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Discovery failed: {result}")
            else:
                discovered.extend(result)

        # Deduplicate by plugin_id (priority order)
        seen = {}
        for plugin in discovered:
            if plugin.id not in seen:
                seen[plugin.id] = plugin
            else:
                logger.debug(f"Skipping duplicate plugin: {plugin.id}")

        return list(seen.values())

    async def _discover_builtin(self) -> list[PluginMetadata]:
        """Discover built-in plugins."""
        builtin_dir = Path(__file__).parent.parent / "plugins" / "builtin"
        if not builtin_dir.exists():
            return []
        return await self._scan_directory(builtin_dir)

    async def _discover_packages(self) -> list[PluginMetadata]:
        """Discover installed package plugins."""
        discovered = []
        for ep in entry_points(group="berg_plugins"):
            try:
                plugin_class = ep.load()
                metadata = self._extract_metadata(plugin_class, ep.name)
                discovered.append(metadata)
            except Exception as e:
                logger.warning(f"Failed to load plugin {ep.name}: {e}")
        return discovered

    async def _discover_local(self) -> list[PluginMetadata]:
        """Discover local directory plugins."""
        if not self.plugin_dir.exists():
            return []
        return await self._scan_directory(self.plugin_dir)

    async def _scan_directory(self, directory: Path) -> list[PluginMetadata]:
        """Scan directory for plugin manifests."""
        discovered = []
        for item in directory.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "plugin.yaml"
            if manifest_path.exists():
                try:
                    metadata = await self._parse_manifest(manifest_path)
                    discovered.append(metadata)
                except Exception as e:
                    logger.warning(f"Failed to parse {manifest_path}: {e}")
        return discovered
```

## [Plugin Metadata](../discovery/plugin_metadata.py)

```python
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
```

## [Registration Process](../discovery/plugin_registry.py)

### [Plugin Registry](../discovery/plugin_registry.py)

```python
class PluginRegistry:
    """Central plugin registry."""

    def __init__(self):
        self._plugins: dict[str, PluginEntry] = {}
        self._capabilities: dict[str, list[PluginCapability]] = {}
        self._lock = asyncio.Lock()

    async def register(self, metadata: PluginMetadata) -> PluginEntry:
        """Register a discovered plugin."""
        async with self._lock:
            if metadata.id in self._plugins:
                raise PluginError(f"Plugin already registered: {metadata.id}")

            entry = PluginEntry(
                metadata=metadata, state=PluginState.DISCOVERED, instance=None
            )

            self._plugins[metadata.id] = entry
            logger.info(f"Registered plugin: {metadata.id} v{metadata.version}")
            return entry

    def get(self, plugin_id: str) -> PluginEntry | None:
        """Get plugin by ID."""
        return self._plugins.get(plugin_id)

    def list_plugins(
        self,
        state: PluginState | None = None,
        source: PluginSource | None = None,
        tag: str | None = None,
    ) -> list[PluginEntry]:
        """List plugins with optional filters."""
        plugins = list(self._plugins.values())

        if state is not None:
            plugins = [p for p in plugins if p.state == state]
        if source is not None:
            plugins = [p for p in plugins if p.metadata.source == source]
        if tag is not None:
            plugins = [p for p in plugins if tag in p.metadata.tags]

        return plugins

    async def register_capability(
        self, plugin_id: str, capability: PluginCapability
    ) -> None:
        """Register a plugin capability."""
        async with self._lock:
            if plugin_id not in self._capabilities:
                self._capabilities[plugin_id] = []
            self._capabilities[plugin_id].append(capability)

    def get_capabilities(
        self, plugin_id: str | None = None, capability_type: str | None = None
    ) -> list[PluginCapability]:
        """Get capabilities with optional filters."""
        if plugin_id:
            caps = self._capabilities.get(plugin_id, [])
        else:
            caps = [c for caps in self._capabilities.values() for c in caps]

        if capability_type:
            caps = [c for c in caps if c.type == capability_type]

        return caps
```

### [Plugin Entry](../discovery/plugin_entry.py)

```python
@dataclass
class PluginEntry:
    """Registry entry for a plugin."""
    
    metadata: PluginMetadata
    state: PluginState
    instance: BergPlugin | None
    
    loaded_at: datetime | None = None
    enabled_at: datetime | None = None
    error: Exception | None = None
    
    def is_enabled(self) -> bool:
        """Check if plugin is enabled."""
        return self.state == PluginState.ENABLED
    
    def is_loaded(self) -> bool:
        """Check if plugin is loaded."""
        return self.state in (PluginState.LOADED, PluginState.ENABLED)
```

## [Backward Compatibility](../discovery/plugin_compat.py)

### [Skill Adapter](../discovery/plugin_compat.py)

Wrap existing skills as plugins:

```python
class SkillPluginAdapter(BergPlugin):
    """Adapter to wrap existing skills as plugins."""

    def __init__(self, skill_path: Path):
        self.skill_path = skill_path
        self.skill_data = None

    async def on_load(self, context: PluginContext) -> None:
        """Load skill content."""
        self.skill_data = parse_skill(self.skill_path)

    def get_capabilities(self) -> list[PluginCapability]:
        """Return skill as a capability."""
        return [
            CapabilityWrapper(
                type="skill",
                id=self.skill_data["name"],
                description=self.skill_data["description"],
                content=self.skill_data["body"],
                deferred=True,
            )
        ]
```

### [MCP Adapter](../discovery/plugin_compat.py)

Wrap MCP servers as plugins:

```python
class MCPPluginAdapter(BergPlugin):
    """Adapter to wrap MCP servers as plugins."""

    def __init__(self, server_config: dict[str, Any]):
        self.config = server_config
        self.toolset = None

    async def on_load(self, context: PluginContext) -> None:
        """Initialize MCP connection."""
        self.toolset = await create_mcp_toolset(self.config)

    def get_capabilities(self) -> list[PluginCapability]:
        """Return MCP tools as capabilities."""
        return [
            ToolCapability(
                type="tool", tool=tool, risk_level="medium", deferred=False
            )
            for tool in self.toolset.tools
        ]
```

## [Performance Optimizations](../discovery/performance_optim.py)

### [Lazy Import](../discovery/performance_optim.py)

```python
def lazy_import_plugin(entry_point: str) -> type[BergPlugin]:
    """Import plugin class only when needed."""
    module_path, class_name = entry_point.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
```

### [Parallel Discovery](../discovery/performance_optim.py)

```python
async def discover_all_parallel() -> list[PluginMetadata]:
    """Discover plugins in parallel."""
    tasks = [discover_builtin(), discover_packages(), discover_local()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        p
        for result in results
        if not isinstance(result, Exception)
        for p in result
    ]
```

### [Caching](../discovery/performance_optim.py)

```python
class PluginCache:
    """Cache for plugin metadata."""
    
    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.cache: dict[str, PluginMetadata] = {}
    
    def load(self) -> None:
        """Load cache from disk."""
        if self.cache_file.exists():
            data = json.loads(self.cache_file.read_text())
            self.cache = {k: PluginMetadata(**v) for k, v in data.items()}
    
    def save(self) -> None:
        """Save cache to disk."""
        data = {k: asdict(v) for k, v in self.cache.items()}
        self.cache_file.write_text(json.dumps(data, indent=2))
    
    def get(self, plugin_id: str, version: str) -> PluginMetadata | None:
        """Get cached metadata."""
        key = f"{plugin_id}@{version}"
        return self.cache.get(key)
    
    def set(self, metadata: PluginMetadata) -> None:
        """Cache metadata."""
        key = f"{metadata.id}@{metadata.version}"
        self.cache[key] = metadata
```

## CLI Commands

```bash
# List all discovered plugins
$ berg-agents plugins list

# Discover and show new plugins
$ berg-agents plugins discover

# Show plugin details
$ berg-agents plugins show <plugin-id>

# Enable/disable plugin
$ berg-agents plugins enable <plugin-id>
$ berg-agents plugins disable <plugin-id>

# Reload plugins (during development)
$ berg-agents plugins reload
```

## Configuration

```yaml
# .berg-agents/bergagents.yaml
plugins:
  # Plugin directory
  plugin_dir: ".berg-agents/plugins"
  
  # Cache directory
  cache_dir: ".cache/plugins"
  
  # Auto-discover on startup
  auto_discover: true
  
  # Discovery sources
  sources:
    builtin: true
    packages: true
    local: true
    remote: false
  
  # Disabled plugins
  disabled:
    - old-plugin
    - deprecated-plugin
```

## Summary

**Discovery sources:** builtin > local > packages > remote

**Discovery flow:** scan → validate → deduplicate → sort → register

**Key features:**
- Multi-source discovery
- Parallel scanning
- Metadata caching
- Backward compatibility adapters
- Hot reload support

**Next:** Plugin lifecycle management (load, enable, disable, unload)
