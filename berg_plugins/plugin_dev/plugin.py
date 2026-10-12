#  Berg Agents is a sophisticated multi-agent system built on Pydantic AI with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  Sofia Billger Bergström
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


#
# # plugin.py
# import logging
# from datetime import datetime
#
# from feat_dev.plugin_dev.plugin_system.lifecycle.bergplugin import BergPlugin
# from feat_dev.plugin_dev.plugin_system.lifecycle.runtime_health import (
#     HealthStatus,
# )
# from feat_dev.plugin_dev.plugin_system.plugin_contract import (
#     PluginContext,
#     ToolCapability,
# )
#
# logger = logging.getLogger(__name__)
#
#
# class MyPlugin(BergPlugin):
#     """My plugin implementation."""
#
#     def __init__(self) -> None:
#         self.settings: MyPluginSettings | None = None
#
#     # === Lifecycle Hooks ===
#
#     async def on_load(self, context: PluginContext) -> None:
#         """Load plugin."""
#         logger.info(f"Loading {context.plugin_id}")
#
#         # Parse settings
#         self.settings = MyPluginSettings(**context.settings)
#
#         # Initialize client, connections, etc.
#         logger.info("Plugin loaded successfully")
#
#     async def on_enable(self, context: PluginContext) -> None:
#         """Enable plugin."""
#         logger.info(f"Enabling {context.plugin_id}")
#
#         # Subscribe to events
#         self.subscribe("agent.task.*", self._on_agent_event)
#
#         # Start background tasks if needed
#
#         # Emit enabled event
#         await self.emit("plugin.myplugin.enabled", {})
#
#     async def on_disable(self, context: PluginContext) -> None:
#         """Disable plugin."""
#         logger.info(f"Disabling {context.plugin_id}")
#
#         # Stop background tasks
#         # Close connections
#
#     async def on_unload(self, context: PluginContext) -> None:
#         """Unload plugin."""
#         logger.info(f"Unloading {context.plugin_id}")
#
#         # Final cleanup
#
#     async def on_error(self, context: PluginContext, error: Exception) -> None:
#         """Handle errors."""
#         logger.error(f"Plugin error: {error}", exc_info=True)
#         await self.emit("plugin.myplugin.error", {"error": str(error)})
#
#     # === Configuration ===
#
#     async def on_config_change(
#         self, context: PluginContext, new_config: dict
#     ) -> None:
#         """Handle configuration changes."""
#         logger.info("Configuration changed")
#
#         # Re-parse settings
#         old_settings = self.settings
#         self.settings = MyPluginSettings(**new_config)
#
#         # Restart connections if needed
#         if old_settings.base_url != self.settings.base_url:
#             # Reconnect with new URL
#             pass
#
#     # === Capabilities ===
#
#     def get_capabilities(self) -> list[ToolCapability]:
#         """Return plugin capabilities."""
#         return [
#             ToolCapability(
#                 type="tool",
#                 tool=create_thing,
#                 risk_level="medium",
#                 deferred=True,
#             ),
#         ]
#
#     def get_settings_schema(self) -> dict | None:
#         """Return settings schema."""
#         return MyPluginSettings.model_json_schema()
#
#     # === Health Check ===
#
#     async def health_check(self, context: PluginContext) -> HealthStatus:
#         """Check plugin health."""
#         try:
#             # Ping API or check connections
#             return HealthStatus(status="healthy", checked_at=datetime.now())
#         except Exception as e:
#             return HealthStatus(status="degraded", message=str(e), checked_at=datetime.now())
#
#     # === Event Handlers ===
#
#     async def _on_agent_event(self, event) -> None:
#         """Handle agent events."""
#         logger.debug(f"Agent event: {event.type}")
#         # React to agent events
