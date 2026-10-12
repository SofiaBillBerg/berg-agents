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

# Runtime health monitoring

import asyncio
import logging

from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_hooks import (
    PluginLifecycle,
)
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_states import (
    PluginState,
)

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Monitor plugin health."""

    def __init__(
        self, lifecycle: PluginLifecycle, interval: float = 60.0
    ) -> None:
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
            try:
                await self.task
            except asyncio.CancelledError:
                pass

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
                    entry.instance.health_check(context),
                    timeout=10.0,
                )

                if status.status == "unhealthy":
                    logger.warning(
                        f"Plugin {entry.metadata.id} unhealthy: {status.message}"
                    )
                    # Optionally disable unhealthy plugins
                    # await self.lifecycle.disable(entry.metadata.id)

            except TimeoutError:
                logger.warning(f"Health check timeout: {entry.metadata.id}")
            except Exception as e:
                logger.error(f"Health check failed: {entry.metadata.id}: {e}")
