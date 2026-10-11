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

#  <one line to give the program's name and a brief idea of what it does.>
#
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

from dataclasses import dataclass
from typing import Any

from feat_dev.plugin_dev.plugin_system.events.event_bus import Event


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


# [Event Schemas](plugin_system/system_events.py#Event-Schemas)


@dataclass
class PluginLifecycleEvent(Event):
    """Plugin lifecycle event."""

    plugin_id: str
    version: str

    def __post_init__(self) -> None:
        self.data["plugin_id"] = self.plugin_id
        self.data["version"] = self.version


@dataclass
class AgentTaskEvent(Event):
    """Agent task event."""

    task_id: str
    agent_name: str
    description: str

    def __post_init__(self) -> None:
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

    def __post_init__(self) -> None:
        self.data.update({
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error})
