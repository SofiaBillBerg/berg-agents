"""Resource management for the plugin system."""

# Resource Management

import asyncio

# Resource Tracking
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PluginResources:
    """Track resources allocated by a plugin."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.tasks: set[asyncio.Task] = set()
        self.connections: list[Any] = []
        self.file_handles: list[Any] = []
        self.timers: list[Any] = []

    def add_task(self, task: asyncio.Task) -> None:
        """Track an async task."""
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

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
