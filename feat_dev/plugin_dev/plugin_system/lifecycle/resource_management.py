"""Resource management for the plugin system."""
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
