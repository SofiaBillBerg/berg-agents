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

import asyncio
from typing import Any

from feat_dev.plugin_dev.plugin_system.events.event_bus import Event, EventBus, EventHandler


# [Request-Response Pattern](../08-plugin-event-system#Request-Response Pattern)


class RequestResponsePattern:
    """Request-response communication pattern."""

    def __init__(self, event_bus: EventBus) -> None:
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


    # # Usage example
    # async def example_request_response() -> None:
    #     pattern = RequestResponsePattern(event_bus=EventBus())
    #
    #     # Plugin A requests data from feat_dev.plugin_dev.plugin B
    #     response = await pattern.request(
    #         target_plugin="berg-plugin-github",
    #         request_type="get_issues",
    #         data={"repo": "org/repo", "state": "open"},
    #     )
    #
    #     print(f"Got {len(response['issues'])} issues")


# [Pub-Sub Pattern](../08-plugin-event-system#Pub-Sub Pattern)


class PubSubChannel:
    """Pub-sub channel for topic-based messaging."""

    def __init__(self, event_bus: EventBus, channel: str) -> None:
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


    # # Usage example
    # notifications = PubSubChannel(event_bus=EventBus(), channel="notifications")
    #
    #
    # # Subscribe
    # async def handle_notification(event: Event) -> None:
    #     print(f"Notification: {event.data}")
    #
    #
    # notifications.subscribe("info", handle_notification)
    #
    # # Publish
    # await notifications.publish(
    #     topic="info", message={"text": "Task completed"}, source="plugin-github"
    # )


# [Event Aggregation](../08-plugin-event-system#Event-Aggregation)


class EventAggregator:
    """Aggregate multiple events into one."""

    def __init__(self, event_bus: EventBus) -> None:
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
