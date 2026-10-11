#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

## Runtime health monitoring

### Health Monitoring

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from attrs import field
from babel.util import UTC

from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_hooks import PluginLifecycle
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_states import PluginState
from feat_dev.plugin_dev.plugin_system.discovery.plugin_entry import PluginEntry

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Plugin health status."""

    status: Literal["healthy", "degraded", "unhealthy"]
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    message: str | None = None
    details: dict[str, Any] | None = None


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


### Hot Reload


class PluginReloader:
    """Hot reload plugins during development."""

    def __init__(self, lifecycle: PluginLifecycle) -> None:
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


### Graceful Degradation


class PluginLoadError:
    """Custom exception for plugin load failures."""

    def __init__(self, message: str):
        super().__init__(message)


async def _enable_partial(entry: PluginEntry):
    """Attempt to enable a plugin with reduced capabilities."""
    # This is a placeholder for partial enable logic
    # For example, disable certain features or capabilities
    logger.info(f"Attempting partial enable for plugin: {entry.metadata.id}")
    # Simulate partial enable
    await asyncio.sleep(1)
    entry.state = PluginState.ENABLED
    logger.info(f"Plugin partially enabled: {entry.metadata.id}")


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
        except Exception as e:
            logger.warning(f"Partial enable failed: {entry.metadata.id}, {e}")
