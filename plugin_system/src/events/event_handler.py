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

"""Event handling, filtering, transformation, and persistence."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# Event Filtering & Transformation
from typing import Any

from plugin_system.events.event_bus import Event, EventBus


class EventFilter:
    """Filter events based on criteria."""

    @staticmethod
    def by_source(source: str) -> Callable[[Event], bool]:
        """Filter by event source."""
        return lambda e: e.source == source

    @staticmethod
    def by_data_field(field: str, value: Any) -> Callable[[Event], bool]:
        """Filter by data field value."""
        return lambda e: e.data.get(field) == value

    @staticmethod
    def combine(*filters: Callable[[Event], bool]) -> Callable[[Event], bool]:
        """Combine multiple filters (AND)."""
        return lambda e: all(f(e) for f in filters)


class EventTransformer:
    """Transform event data."""

    @staticmethod
    def map_fields(mapping: dict[str, str]) -> Callable[[Event], Event]:
        """Map event data fields."""

        def transform(event: Event) -> Event:
            """Transform event data fields based on mapping."""
            new_data = {}
            for old_key, new_key in mapping.items():
                if old_key in event.data:
                    new_data[new_key] = event.data[old_key]
            event.data = new_data
            return event

        return transform

    @staticmethod
    def enrich(enricher: Callable[[dict], dict]) -> Callable[[Event], Event]:
        """Enrich event data."""

        def transform(event: Event) -> Event:
            event.data = enricher(event.data)
            return event

        return transform


# Event Persistence


class EventStore:
    """Persistent event storage."""

    def __init__(self, db_path: Path) -> None:
        """Initialize event store with database path."""
        self.db_path = db_path

    async def save(self, event: Event) -> None:
        """Save event to persistent storage."""
        # Implementation would use SQLite, PostgreSQL, etc.

    async def query(
        self,
        event_type: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query stored events."""

    async def replay(
        self, event_bus: EventBus, since: datetime | None = None
    ) -> None:
        """Replay events from storage."""
        events = await self.query(since=since)
        for event in events:
            await event_bus.emit(event.type, event.data, source=event.source)


# Event Monitoring


class EventMonitor:
    """Monitor event bus activity."""

    def __init__(self, event_bus: EventBus) -> None:
        """Initialize event monitor with event bus."""
        self.event_bus = event_bus
        self.stats: dict[str, int] = {}

    async def start(self) -> None:
        """Start monitoring."""
        self.event_bus.subscribe("*", self._track_event)

    async def _track_event(self, event: Event) -> None:
        """Track event statistics."""
        self.stats[event.type] = self.stats.get(event.type, 0) + 1

    def get_stats(self) -> dict[str, int]:
        """Get event statistics."""
        return self.stats.copy()
