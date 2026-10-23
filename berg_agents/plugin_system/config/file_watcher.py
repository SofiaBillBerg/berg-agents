# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

#  Berg Agents Plugin System - File Watcher
#
"""File watching utilities for configuration hot-reloading."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileWatcher:
    """Watch a file for changes and trigger callbacks."""

    def __init__(self, filepath: Path) -> None:
        """Initialize the file watcher."""
        self.filepath = filepath
        self.last_mtime = self._get_mtime()
        self.callbacks: list[Callable[[], Awaitable[None]]] = []
        self.task: asyncio.Task | None = None
        self._running = False

    def _get_mtime(self) -> float:
        """Get file modification time."""
        try:
            return (
                self.filepath.stat().st_mtime if self.filepath.exists() else 0.0
            )
        except Exception:
            return 0.0

    def on_change(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register a callback for file changes."""
        self.callbacks.append(callback)

    async def start(self) -> None:
        """Start watching the file."""
        if self._running:
            return
        self._running = True
        self.task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop watching the file."""
        self._running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        """Main watch loop."""
        while self._running:
            try:
                current_mtime = self._get_mtime()
                if current_mtime != self.last_mtime:
                    logger.info(f"File changed: {self.filepath}")
                    self.last_mtime = current_mtime
                    for callback in self.callbacks:
                        try:
                            await callback()
                        except Exception as e:
                            logger.exception(f"Error in callback: {e}")
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.exception(f"Error in file watcher: {e}")
                await asyncio.sleep(1.0)


class FileSystemWatcher:
    """Watch multiple files for changes."""

    def __init__(self) -> None:
        """Initialize the file system watcher."""
        self.watchers: dict[str, FileWatcher] = {}

    async def watch_file(
        self, filepath: Path, callback: Callable[[], Awaitable[None]]
    ) -> None:
        """Watch a file for changes."""
        key = str(filepath)
        if key not in self.watchers:
            watcher = FileWatcher(filepath)
            self.watchers[key] = watcher
            await watcher.start()
        self.watchers[key].on_change(callback)

    async def stop_all(self) -> None:
        """Stop all watchers."""
        for watcher in self.watchers.values():
            await watcher.stop()
        self.watchers.clear()
