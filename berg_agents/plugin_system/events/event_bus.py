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

"""Event bus for plugin communication."""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base event class."""

    type: str  # Event type (e.g., "plugin.loaded")
    source: str  # Source plugin/system ID
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None  # For request/response patterns

    def matches(self, pattern: str) -> bool:
        """Check if event type matches pattern.

        Supports wildcards: "plugin.*", "agent.task.*"
        """
        import fnmatch

        return fnmatch.fnmatch(self.type, pattern)


# Type alias for event handlers - defined after Event class
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Async event bus for plugin communication."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._processing_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # Event history for replay
        self._history: list[Event] = []
        self._max_history = 1000

    async def initialize(self) -> None:
        """Initialize and start event processing."""
        await self.start()

    async def start(self) -> None:
        """Start event processing."""
        self._processing_task = asyncio.create_task(self._process_events())
        logger.info("Event bus started")

    async def shutdown(self) -> None:
        """Shutdown event processing."""
        await self.stop()

    async def stop(self) -> None:
        """Stop event processing."""
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
        logger.info("Event bus stopped")

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        source: str = "system",
        correlation_id: str | None = None,
    ) -> None:
        """Emit an event.

        Args:
            event_type: Event type string
            data: Event data
            source: Event source ID
            correlation_id: Correlation ID for request/response
        """
        event = Event(
            type=event_type,
            source=source,
            data=data or {},
            correlation_id=correlation_id,
        )

        # Add to history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        # Queue for processing
        await self._queue.put(event)

        logger.debug(f"Event emitted: {event_type} from {source}")

    def subscribe(
        self, event_pattern: str, handler: EventHandler, priority: int = 0
    ) -> str:
        """Subscribe to events matching pattern.

        Args:
            event_pattern: Event type pattern (supports wildcards)
            handler: Async handler function
            priority: Higher priority handlers run first

        Returns:
            Subscription ID
        """
        subscription_id = f"sub_{id(handler)}"

        if event_pattern not in self._handlers:
            self._handlers[event_pattern] = []

        self._handlers[event_pattern].append(handler)

        # Sort by priority
        self._handlers[event_pattern].sort(
            key=lambda h: getattr(h, "_priority", 0), reverse=True
        )

        logger.debug(f"Subscribed to {event_pattern}: {subscription_id}")
        return subscription_id

    def unsubscribe(self, event_pattern: str, handler: EventHandler) -> None:
        """Unsubscribe from events."""
        if event_pattern in self._handlers:
            self._handlers[event_pattern] = [
                h for h in self._handlers[event_pattern] if h != handler
            ]
            logger.debug(f"Unsubscribed from {event_pattern}")

    async def _process_events(self) -> None:
        """Process events from queue."""
        while True:
            try:
                event = await self._queue.get()
                await self._dispatch_event(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}")

    async def _dispatch_event(self, event: Event) -> None:
        """Dispatch event to matching handlers."""
        handlers_to_call = []

        # Find matching handlers
        for pattern, handlers in self._handlers.items():
            if event.matches(pattern):
                handlers_to_call.extend(handlers)

        if not handlers_to_call:
            logger.debug(f"No handlers for event: {event.type}")
            return

        # Call handlers concurrently
        tasks = [handler(event) for handler in handlers_to_call]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Handler {handlers_to_call[i]} failed for {event.type}: {result}"
                )

    async def wait_for(
        self,
        event_pattern: str,
        timeout: float | None = None,
        filter_fn: Callable[[Event], bool] | None = None,
    ) -> Event:
        """Wait for a specific event.

        Args:
            event_pattern: Event type pattern
            timeout: Timeout in seconds
            filter_fn: Additional filter function

        Returns:
            Matching event

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        future: asyncio.Future[Event] = asyncio.Future()

        async def handler(event: Event) -> None:
            """Handle incoming events.

            :param event:  The event to handle
            """
            if (filter_fn is None or filter_fn(event)) and not future.done():
                future.set_result(event)

        self.subscribe(event_pattern, handler)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.unsubscribe(event_pattern, handler)

    def get_history(
        self,
        event_type: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get event history with filters."""
        events = self._history.copy()

        if event_type:
            events = [e for e in events if e.type == event_type]
        if source:
            events = [e for e in events if e.source == source]
        if since:
            events = [e for e in events if e.timestamp >= since]

        return events[-limit:]
