# Plugin Event System & Inter-Plugin Communication

*Generated: 2026-10-10*

## Overview

The event system enables plugins to communicate with each other and react to system events through a typed, async event bus with subscriptions, filters, and guaranteed delivery.

## Event Architecture

### [Event Bus](../events/event_bus.py)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable
import asyncio
from enum import Enum

EventHandler = Callable[[Event], Awaitable[None]]


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


class EventBus:
    """Async event bus for plugin communication."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._processing_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # Event history for replay
        self._history: list[Event] = []
        self._max_history = 1000

    async def start(self) -> None:
        """Start event processing."""
        self._processing_task = asyncio.create_task(self._process_events())
        logger.info("Event bus started")

    async def stop(self) -> None:
        """Stop event processing."""
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
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
            if filter_fn is None or filter_fn(event):
                if not future.done():
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
```

## [System Events](../events/system_events.py)

### [Core Events](../events/system_events.py)

```python
class SystemEvents:
    """System event types."""
    
    # Plugin lifecycle
    PLUGIN_DISCOVERED = "plugin.discovered"
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_ENABLED = "plugin.enabled"
    PLUGIN_DISABLED = "plugin.disabled"
    PLUGIN_UNLOADED = "plugin.unloaded"
    PLUGIN_ERROR = "plugin.error"
    PLUGIN_CONFIG_CHANGED = "plugin.config.changed"
    
    # Agent lifecycle
    AGENT_TASK_STARTED = "agent.task.started"
    AGENT_TASK_COMPLETED = "agent.task.completed"
    AGENT_TASK_FAILED = "agent.task.failed"
    AGENT_TOOL_CALLED = "agent.tool.called"
    AGENT_TOOL_COMPLETED = "agent.tool.completed"
    
    # System lifecycle
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"
    SYSTEM_ERROR = "system.error"
    
    # User interaction
    USER_APPROVED = "user.approved"
    USER_REJECTED = "user.rejected"
```

### [Event Schemas](../events/system_events.py)

```python
@dataclass
class PluginLifecycleEvent(Event):
    """Plugin lifecycle event."""

    plugin_id: str
    version: str

    def __post_init__(self):
        self.data["plugin_id"] = self.plugin_id
        self.data["version"] = self.version


@dataclass
class AgentTaskEvent(Event):
    """Agent task event."""

    task_id: str
    agent_name: str
    description: str

    def __post_init__(self):
        self.data.update({
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "description": self.description})


@dataclass
class ToolCallEvent(Event):
    """Tool call event."""

    tool_name: str
    args: dict[str, Any]
    result: Any | None = None
    error: str | None = None

    def __post_init__(self):
        self.data.update({
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error})
```

## Plugin Event Integration

### [Event Mixin for Plugins](../events/event_integration.py)

```python
class EventEmitter:
    """Mixin for plugins to emit events."""

    def __init__(self, plugin_id: str, event_bus: EventBus):
        self.plugin_id = plugin_id
        self.event_bus = event_bus

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit an event from this plugin."""
        await self.event_bus.emit(
            event_type=event_type,
            data=data,
            source=self.plugin_id,
            correlation_id=correlation_id,
        )

    def subscribe(
        self, event_pattern: str, handler: EventHandler, priority: int = 0
    ) -> str:
        """Subscribe to events."""
        return self.event_bus.subscribe(event_pattern, handler, priority)

    def unsubscribe(self, event_pattern: str, handler: EventHandler) -> None:
        """Unsubscribe from events."""
        self.event_bus.unsubscribe(event_pattern, handler)


class BergPlugin(EventEmitter, ABC):
    """Base plugin with event support."""

    def __init__(self):
        # EventEmitter initialized by context in on_load
        pass

    async def on_load(self, context: PluginContext) -> None:
        """Initialize event emitter."""
        EventEmitter.__init__(
            self, plugin_id=context.plugin_id, event_bus=context.event_bus
        )
```

### Example Plugin Using Events

```python
class GithubPlugin(BergPlugin):
    """GitHub plugin with event integration."""

    async def on_enable(self, context: PluginContext) -> None:
        """Subscribe to relevant events."""
        # Listen for agent task events
        self.subscribe("agent.task.*", self._on_agent_task)

        # Listen for other plugins
        self.subscribe("plugin.slack.message", self._on_slack_message)

    async def _on_agent_task(self, event: Event) -> None:
        """Handle agent task events."""
        if event.type == "agent.task.completed":
            task_id = event.data.get("task_id")
            logger.info(f"GitHub plugin notified of task completion: {task_id}")

            # Could create GitHub issue, PR, etc.
            await self._maybe_create_issue(event.data)

    async def _on_slack_message(self, event: Event) -> None:
        """Handle Slack messages."""
        message = event.data.get("text", "")

        # Parse GitHub mentions
        if "github" in message.lower():
            await self.emit(
                "plugin.github.mention",
                {"message": message, "source_event": event.type},
            )

    async def create_issue(self, title: str, body: str) -> str:
        """Create a GitHub issue and emit event."""
        # Create issue via API
        issue_url = "https://github.com/org/repo/issues/123"

        # Emit event
        await self.emit(
            "plugin.github.issue.created", {"title": title, "url": issue_url}
        )

        return issue_url
```

## [Inter-Plugin Communication Patterns](../inter_plugin_communication.py)

### [Request-Response Pattern](../inter_plugin_communication.py)

```python
class RequestResponsePattern:
    """Request-response communication pattern."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def request(
        self,
        target_plugin: str,
        request_type: str,
        data: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send request and wait for response.

        Args:
            target_plugin: Target plugin ID
            request_type: Request type
            data: Request data
            timeout: Response timeout

        Returns:
            Response data
        """
        import uuid

        correlation_id = str(uuid.uuid4())

        # Emit request
        await self.event_bus.emit(
            event_type=f"plugin.{target_plugin}.request.{request_type}",
            data=data,
            correlation_id=correlation_id,
        )

        # Wait for response
        response_event = await self.event_bus.wait_for(
            event_pattern=f"plugin.{target_plugin}.response.{request_type}",
            timeout=timeout,
            filter_fn=lambda e: e.correlation_id == correlation_id,
        )

        return response_event.data

    async def respond(
        self, request_event: Event, response_data: dict[str, Any]
    ) -> None:
        """Respond to a request.

        Args:
            request_event: Original request event
            response_data: Response data
        """
        # Extract request type
        request_type = request_event.type.split(".")[-1]

        # Emit response
        await self.event_bus.emit(
            event_type=f"plugin.{request_event.source}.response.{request_type}",
            data=response_data,
            correlation_id=request_event.correlation_id,
        )


# Usage example
async def example_request_response():
    pattern = RequestResponsePattern(event_bus)

    # Plugin A requests data from Plugin B
    response = await pattern.request(
        target_plugin="berg-plugin-github",
        request_type="get_issues",
        data={"repo": "org/repo", "state": "open"},
    )

    print(f"Got {len(response['issues'])} issues")
```

### [Pub-Sub Pattern](../inter_plugin_communication.py)

```python
class PubSubChannel:
    """Pub-sub channel for topic-based messaging."""

    def __init__(self, event_bus: EventBus, channel: str):
        self.event_bus = event_bus
        self.channel = channel

    async def publish(
        self, topic: str, message: dict[str, Any], source: str
    ) -> None:
        """Publish message to topic."""
        await self.event_bus.emit(
            event_type=f"channel.{self.channel}.{topic}",
            data=message,
            source=source,
        )

    def subscribe(self, topic: str, handler: EventHandler) -> str:
        """Subscribe to topic."""
        pattern = f"channel.{self.channel}.{topic}"
        return self.event_bus.subscribe(pattern, handler)


# Usage example
notifications = PubSubChannel(event_bus, "notifications")


# Subscribe
async def handle_notification(event: Event):
    print(f"Notification: {event.data}")


notifications.subscribe("info", handle_notification)

# Publish
await notifications.publish(
    topic="info", message={"text": "Task completed"}, source="plugin-github"
)
```

### [Event Aggregation](../inter_plugin_communication.py)

```python
class EventAggregator:
    """Aggregate multiple events into one."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def aggregate(
        self, event_patterns: list[str], output_event: str, window: float = 5.0
    ) -> None:
        """Aggregate events within time window.

        Args:
            event_patterns: Event patterns to aggregate
            output_event: Output event type
            window: Time window in seconds
        """
        collected: list[Event] = []

        async def collect(event: Event) -> None:
            collected.append(event)

        # Subscribe to all patterns
        for pattern in event_patterns:
            self.event_bus.subscribe(pattern, collect)

        # Wait for window
        await asyncio.sleep(window)

        # Emit aggregated event
        if collected:
            await self.event_bus.emit(
                event_type=output_event,
                data={
                    "count": len(collected),
                    "events": [
                        {"type": e.type, "data": e.data} for e in collected
                    ]},
            )
```

## [Event Filtering & Transformation](../events)

```python
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
```

## [Event Persistence](../events)

```python
class EventStore:
    """Persistent event storage."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def save(self, event: Event) -> None:
        """Save event to persistent storage."""
        # Implementation would use SQLite, PostgreSQL, etc.
        pass

    async def query(
        self,
        event_type: str | None = None,
        source: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query stored events."""
        pass

    async def replay(
        self, event_bus: EventBus, since: datetime | None = None
    ) -> None:
        """Replay events from storage."""
        events = await self.query(since=since)
        for event in events:
            await event_bus.emit(event.type, event.data, source=event.source)
```

## [Event Monitoring](../events)

```python
class EventMonitor:
    """Monitor event bus activity."""
    
    def __init__(self, event_bus: EventBus):
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
```

## Configuration

```yaml
# .berg-agents/bergagents.yaml
plugins:
  events:
    # Event history size
    max_history: 1000
    
    # Enable event persistence
    persist_events: true
    
    # Event store path
    event_store: "data/events.db"
    
    # Log all events
    debug_events: false
```

## Summary

**Event bus:** Async, typed, pattern matching, history

**Patterns:** Pub-sub, request-response, aggregation

**Key features:**
- Wildcard pattern matching
- Priority handlers
- Correlation IDs
- Event filtering & transformation
- Event persistence
- Request-response pattern
- Pub-sub channels

**Next:** Plugin manifest schema and validation
