# Plugin Lifecycle Management

*Generated: 2026-10-10*

## Overview

The plugin lifecycle system manages state transitions, resource allocation, error handling, and graceful degradation throughout a plugin's lifetime.

## [Lifecycle States](../lifecycle/lifecycle_states.py)

```python
from enum import Enum


class PluginState(str, Enum):
    """Plugin lifecycle states."""

    DISCOVERED = "discovered"  # Found but not loaded
    LOADING = "loading"  # Import in progress
    LOADED = "loaded"  # Manifest parsed, code imported
    ENABLING = "enabling"  # Activation in progress
    ENABLED = "enabled"  # Active and available
    DISABLING = "disabling"  # Deactivation in progress
    DISABLED = "disabled"  # Present but inactive
    UNLOADING = "unloading"  # Cleanup in progress
    ERROR = "error"  # Failed to load or crashed
    DEPRECATED = "deprecated"  # Marked for removal
```

## State Transitions

```
DISCOVERED
    ↓ load()
LOADING
    ↓ on_load() success
LOADED
    ↓ enable()
ENABLING
    ↓ on_enable() success
ENABLED ⟷ disable()/enable()
    ↓ disable()
DISABLING
    ↓ on_disable() success
DISABLED
    ↓ unload()
UNLOADING
    ↓ on_unload() success
[removed from registry]

ERROR can occur from any state
DEPRECATED → eventual unload
```

## [Lifecycle Hooks](../lifecycle/lifecycle_hooks.py)

### [Hook Interface](../lifecycle/bergplugin.py)

```python
class BergPlugin(ABC):
    """Base plugin interface with lifecycle hooks."""
    
    @abstractmethod
    async def on_load(self, context: PluginContext) -> None:
        """Called when plugin is loaded.
        
        Initialize plugin, parse configuration, validate dependencies.
        Do NOT start services or register capabilities here.
        
        Raises:
            PluginLoadError: If plugin cannot be loaded
        """
        
    async def on_enable(self, context: PluginContext) -> None:
        """Called when plugin is enabled.
        
        Start services, register capabilities, connect to external resources.
        
        Raises:
            PluginEnableError: If plugin cannot be enabled
        """
        
    async def on_disable(self, context: PluginContext) -> None:
        """Called when plugin is disabled.
        
        Stop services, unregister capabilities, disconnect resources.
        Should be idempotent - safe to call multiple times.
        """
        
    async def on_unload(self, context: PluginContext) -> None:
        """Called when plugin is unloaded.
        
        Final cleanup, close connections, free resources.
        Should be idempotent - safe to call multiple times.
        """
        
    async def on_error(self, context: PluginContext, error: Exception) -> None:
        """Called when plugin encounters an error.
        
        Log error, attempt recovery, notify users.
        """
        
    async def health_check(self, context: PluginContext) -> HealthStatus:
        """Check plugin health.
        
        Returns:
            HealthStatus with status and optional message
        """
        return HealthStatus(status="healthy")
```

### [Hook Execution](../lifecycle/lifecycle_hooks.py)

```python
class PluginLifecycle:
    """Manages plugin lifecycle transitions."""

    def __init__(
        self,
        registry: PluginRegistry,
        event_bus: EventBus,
        config: dict[str, Any],
    ):
        self.registry = registry
        self.event_bus = event_bus
        self.config = config
        self.timeout = config.get("hook_timeout", 30.0)

    async def load(self, plugin_id: str) -> None:
        """Load a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state != PluginState.DISCOVERED:
            logger.warning(f"Plugin {plugin_id} already in state {entry.state}")
            return

        # Transition to LOADING
        await self._set_state(entry, PluginState.LOADING)

        try:
            # Import plugin class
            plugin_class = self._import_plugin(entry.metadata.entry_point)

            # Instantiate plugin
            instance = plugin_class()
            entry.instance = instance

            # Create context
            context = await self._create_context(entry)

            # Call on_load hook with timeout
            await asyncio.wait_for(
                instance.on_load(context), timeout=self.timeout
            )

            # Transition to LOADED
            await self._set_state(entry, PluginState.LOADED)
            entry.loaded_at = datetime.now()

            # Emit event
            await self.event_bus.emit(
                "plugin.loaded",
                {"plugin_id": plugin_id, "version": entry.metadata.version},
            )

            logger.info(f"Loaded plugin: {plugin_id}")

        except asyncio.TimeoutError:
            await self._handle_error(
                entry, PluginLoadError(f"Load timeout: {plugin_id}")
            )
        except Exception as e:
            await self._handle_error(
                entry, PluginLoadError(f"Load failed: {e}")
            )

    async def enable(self, plugin_id: str) -> None:
        """Enable a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state == PluginState.ENABLED:
            logger.debug(f"Plugin {plugin_id} already enabled")
            return

        if entry.state != PluginState.LOADED:
            # Auto-load if needed
            if entry.state == PluginState.DISCOVERED:
                await self.load(plugin_id)
            else:
                raise PluginStateError(
                    f"Cannot enable plugin in state {entry.state}"
                )

        # Transition to ENABLING
        await self._set_state(entry, PluginState.ENABLING)

        try:
            context = await self._create_context(entry)

            # Call on_enable hook
            await asyncio.wait_for(
                entry.instance.on_enable(context), timeout=self.timeout
            )

            # Register capabilities
            capabilities = entry.instance.get_capabilities()
            for cap in capabilities:
                await self.registry.register_capability(plugin_id, cap)
                await self._register_capability_with_system(entry, cap)

            # Transition to ENABLED
            await self._set_state(entry, PluginState.ENABLED)
            entry.enabled_at = datetime.now()
            entry.metadata.enabled = True

            # Emit event
            await self.event_bus.emit(
                "plugin.enabled",
                {"plugin_id": plugin_id, "capabilities": len(capabilities)},
            )

            logger.info(f"Enabled plugin: {plugin_id}")

        except asyncio.TimeoutError:
            await self._handle_error(
                entry, PluginEnableError(f"Enable timeout: {plugin_id}")
            )
        except Exception as e:
            await self._handle_error(
                entry, PluginEnableError(f"Enable failed: {e}")
            )

    async def disable(self, plugin_id: str) -> None:
        """Disable a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state != PluginState.ENABLED:
            logger.debug(f"Plugin {plugin_id} not enabled")
            return

        # Transition to DISABLING
        await self._set_state(entry, PluginState.DISABLING)

        try:
            context = await self._create_context(entry)

            # Unregister capabilities first
            capabilities = self.registry.get_capabilities(plugin_id)
            for cap in capabilities:
                await self._unregister_capability_from_system(entry, cap)

            # Call on_disable hook
            await asyncio.wait_for(
                entry.instance.on_disable(context), timeout=self.timeout
            )

            # Transition to DISABLED
            await self._set_state(entry, PluginState.DISABLED)
            entry.enabled_at = None
            entry.metadata.enabled = False

            # Emit event
            await self.event_bus.emit(
                "plugin.disabled", {"plugin_id": plugin_id}
            )

            logger.info(f"Disabled plugin: {plugin_id}")

        except asyncio.TimeoutError:
            logger.error(
                f"Disable timeout for {plugin_id}, forcing state change"
            )
            await self._set_state(entry, PluginState.ERROR)
        except Exception as e:
            logger.error(f"Disable failed for {plugin_id}: {e}")
            await self._set_state(entry, PluginState.ERROR)

    async def unload(self, plugin_id: str) -> None:
        """Unload a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        # Disable first if enabled
        if entry.state == PluginState.ENABLED:
            await self.disable(plugin_id)

        if entry.state not in (
            PluginState.LOADED,
            PluginState.DISABLED,
            PluginState.ERROR,
        ):
            logger.debug(
                f"Plugin {plugin_id} cannot be unloaded from state {entry.state}"
            )
            return

        # Transition to UNLOADING
        await self._set_state(entry, PluginState.UNLOADING)

        try:
            if entry.instance:
                context = await self._create_context(entry)

                # Call on_unload hook
                await asyncio.wait_for(
                    entry.instance.on_unload(context), timeout=self.timeout
                )

            # Remove from registry
            await self.registry.unregister(plugin_id)

            # Emit event
            await self.event_bus.emit(
                "plugin.unloaded", {"plugin_id": plugin_id}
            )

            logger.info(f"Unloaded plugin: {plugin_id}")

        except asyncio.TimeoutError:
            logger.error(f"Unload timeout for {plugin_id}, forcing removal")
            await self.registry.unregister(plugin_id)
        except Exception as e:
            logger.error(f"Unload failed for {plugin_id}: {e}")
            await self.registry.unregister(plugin_id)

    async def _handle_error(self, entry: PluginEntry, error: Exception) -> None:
        """Handle plugin error."""
        logger.error(f"Plugin error: {entry.metadata.id}: {error}")

        # Store error
        entry.error = error

        # Transition to ERROR state
        await self._set_state(entry, PluginState.ERROR)

        # Call on_error hook if instance exists
        if entry.instance:
            try:
                context = await self._create_context(entry)
                await entry.instance.on_error(context, error)
            except Exception as e:
                logger.error(f"on_error hook failed: {e}")

        # Emit event
        await self.event_bus.emit(
            "plugin.error",
            {"plugin_id": entry.metadata.id, "error": str(error)},
        )

    async def _set_state(self, entry: PluginEntry, state: PluginState) -> None:
        """Set plugin state."""
        old_state = entry.state
        entry.state = state
        logger.debug(f"Plugin {entry.metadata.id}: {old_state} → {state}")
```

## [Resource Management](../lifecycle/resource_management.py)

### [Resource Tracking](../lifecycle/resource_management.py)

```python
class PluginResources:
    """Track resources allocated by a plugin."""
    
    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.tasks: set[asyncio.Task] = set()
        self.connections: list[Any] = []
        self.file_handles: list[Any] = []
        self.timers: list[Any] = []
    
    def add_task(self, task: asyncio.Task) -> None:
        """Track an async task."""
        self.tasks.add(task)
        task.add_done_callback(lambda t: self.tasks.discard(t))
    
    def add_connection(self, conn: Any) -> None:
        """Track a network connection."""
        self.connections.append(conn)
    
    async def cleanup(self) -> None:
        """Clean up all resources."""
        # Cancel tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Close connections
        for conn in self.connections:
            try:
                await conn.close()
            except Exception as e:
                logger.warning(f"Failed to close connection: {e}")
        
        # Close file handles
        for fh in self.file_handles:
            try:
                fh.close()
            except Exception as e:
                logger.warning(f"Failed to close file: {e}")
```

## [Runtime health monitoring](../lifecycle/runtime_health.py)

### [Health Monitoring](../lifecycle/runtime_health.py)

```python
@dataclass
class HealthStatus:
    """Plugin health status."""

    status: Literal["healthy", "degraded", "unhealthy"]
    message: str | None = None
    details: dict[str, Any] | None = None
    checked_at: datetime = field(default_factory=datetime.now)


class HealthMonitor:
    """Monitor plugin health."""

    def __init__(self, lifecycle: PluginLifecycle, interval: float = 60.0):
        self.lifecycle = lifecycle
        self.interval = interval
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start health monitoring."""
        self.task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop health monitoring."""
        if self.task:
            self.task.cancel()
            await self.task

    async def _monitor_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await asyncio.sleep(self.interval)
                await self._check_all_plugins()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")

    async def _check_all_plugins(self) -> None:
        """Check health of all enabled plugins."""
        plugins = self.lifecycle.registry.list_plugins(
            state=PluginState.ENABLED
        )

        for entry in plugins:
            try:
                context = await self.lifecycle._create_context(entry)
                status = await asyncio.wait_for(
                    entry.instance.health_check(context), timeout=10.0
                )

                if status.status == "unhealthy":
                    logger.warning(
                        f"Plugin {entry.metadata.id} unhealthy: {status.message}"
                    )
                    # Optionally disable unhealthy plugins
                    # await self.lifecycle.disable(entry.metadata.id)

            except asyncio.TimeoutError:
                logger.warning(f"Health check timeout: {entry.metadata.id}")
            except Exception as e:
                logger.error(f"Health check failed: {entry.metadata.id}: {e}")
```

### [Hot Reload](../lifecycley)

```python
class PluginReloader:
    """Hot reload plugins during development."""
    
    def __init__(self, lifecycle: PluginLifecycle):
        self.lifecycle = lifecycle
        self.watchers: dict[str, FileSystemWatcher] = {}
    
    async def watch(self, plugin_id: str) -> None:
        """Watch plugin for changes and auto-reload."""
        entry = self.lifecycle.registry.get(plugin_id)
        if not entry or not entry.metadata.path:
            raise ValueError(f"Cannot watch plugin: {plugin_id}")
        
        watcher = FileSystemWatcher(entry.metadata.path)
        watcher.on_change(lambda: self._reload(plugin_id))
        self.watchers[plugin_id] = watcher
        await watcher.start()
    
    async def _reload(self, plugin_id: str) -> None:
        """Reload a plugin."""
        logger.info(f"Reloading plugin: {plugin_id}")
        
        try:
            # Unload
            await self.lifecycle.unload(plugin_id)
            
            # Rediscover
            # ... (would need to re-run discovery for this plugin)
            
            # Load and enable
            await self.lifecycle.load(plugin_id)
            await self.lifecycle.enable(plugin_id)
            
            logger.info(f"Plugin reloaded: {plugin_id}")
            
        except Exception as e:
            logger.error(f"Reload failed: {plugin_id}: {e}")
```

### [Graceful Degradation](../lifecycley)

```python
class DegradationStrategy:
    """Handle plugin failures gracefully."""

    @staticmethod
    async def handle_load_failure(entry: PluginEntry, error: Exception) -> None:
        """Handle plugin load failure."""
        logger.error(f"Plugin load failed: {entry.metadata.id}: {error}")

        # Mark as optional if not critical
        if not entry.metadata.get("critical", False):
            logger.info(f"Continuing without plugin: {entry.metadata.id}")
            return

        # For critical plugins, raise
        raise PluginLoadError(
            f"Critical plugin failed to load: {entry.metadata.id}"
        ) from error

    @staticmethod
    async def handle_enable_failure(
        entry: PluginEntry, error: Exception
    ) -> None:
        """Handle plugin enable failure."""
        logger.error(f"Plugin enable failed: {entry.metadata.id}: {error}")

        # Try partial enable - load without some capabilities
        try:
            await _enable_partial(entry)
            logger.info(f"Plugin partially enabled: {entry.metadata.id}")
        except Exception:
            logger.warning(f"Partial enable failed: {entry.metadata.id}")
```

## Summary

**States:** discovered → loading → loaded → enabling → enabled ⟷ disabled → unloading

**Hooks:** on_load, on_enable, on_disable, on_unload, on_error, health_check

**Key features:**
- Async lifecycle transitions
- Timeout protection
- Resource tracking and cleanup
- Health monitoring
- Hot reload (development)
- Graceful degradation

**Next:** Dependency resolution and version management
