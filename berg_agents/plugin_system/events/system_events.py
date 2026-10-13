"""System events for the plugin system."""

from dataclasses import dataclass
from typing import Any

from berg_agents.plugin_system.events.event_bus import Event


class SystemEvents:
    """System event types."""

    # Plugin lifecycle
    PLUGIN_DISCOVERED = "plugin.discovered"
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_ENABLED = "plugin.enabled"
    PLUGIN_DISABLED = "plugin.disabled"
    PLUGIN_UNLOADED = "plugin.unloaded"
    PLUGIN_ERROR = "plugin.error"
    PLUGIN_CONFIG_CHANGED = "plugin..berg_config.changed"

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


# [Event Schemas](plugin_system/system_events.py#Event-Schemas)


@dataclass
class PluginLifecycleEvent(Event):
    """Plugin lifecycle event."""

    plugin_id: str = "plugin_id"
    version: str = "version"

    def __post_init__(self) -> None:
        self.data["plugin_id"] = self.plugin_id
        self.data["version"] = self.version


@dataclass
class AgentTaskEvent(Event):
    """Agent task event."""

    task_id: str = "task_id"
    agent_name: str = "agent_name"
    description: str = "description"

    def __post_init__(self) -> None:
        self.data.update({
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "description": self.description})


@dataclass
class ToolCallEvent(Event):
    """Tool call event."""

    tool_name: str = "tool_name"
    args: dict[str, Any] | None = None
    result: Any | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.data.update({
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error})
