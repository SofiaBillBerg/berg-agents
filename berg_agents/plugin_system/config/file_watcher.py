#  Berg Agents Plugin System - File Watcher
#
"""File watching utilities for configuration hot-reloading."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class FileWatcher:
    """Watch a file for changes and trigger callbacks."""

    def __init__(self, filepath: Path) -> None:
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
                            logger.error(f"Error in callback: {e}")
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error in file watcher: {e}")
                await asyncio.sleep(1.0)


class FileSystemWatcher:
    """Watch multiple files for changes."""

    def __init__(self) -> None:
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
