"""Configuration manager for the plugin system."""
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

# Configuration Manager
import logging
import os
from pathlib import Path
import re
from typing import Any

from jsonschema import ValidationError, validate
import yaml

from feat_dev.plugin_dev.plugin_system.exceptions import ConfigValidationError
from feat_dev.plugin_dev.plugin_system.config.file_watcher import FileWatcher
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_hooks import PluginLifecycle

logger = logging.getLogger(__name__)


class PluginConfigManager:
    """Manage plugin configurations."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or Path.home() / ".berg_agents"
        self._cache: dict[str, dict[str, Any]] = {}
        self._env_pattern = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)}")
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the configuration manager."""
        if self._initialized:
            return

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "plugins").mkdir(exist_ok=True)

        self._initialized = True
        logger.info(f"Configuration manager initialized: {self.config_dir}")

    def get_plugin_settings(self, plugin_id: str) -> dict[str, Any]:
        """Get plugin settings from cache or return empty dict.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin settings dictionary
        """
        return self._cache.get(plugin_id, {})

    async def load_config(
            self,
            plugin_id: str,
            schema: dict[str, Any] | None = None,
            defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load and validate plugin configuration.

        Args:
            plugin_id: Plugin ID
            schema: JSON schema for validation
            defaults: Default values

        Returns:
            Validated configuration dict
        """
        # Start with defaults
        config = dict(defaults) if defaults else {}

        # Load from user config file
        user_config = await self._load_user_config(plugin_id)
        if user_config:
            self._deep_merge(config, user_config)

        # Load from environment variables
        env_config = self._load_env_config(plugin_id)
        if env_config:
            self._deep_merge(config, env_config)

        # Expand environment variable references
        config = self._expand_env_vars(config)

        # Validate against schema
        if schema:
            try:
                validate(instance=config, schema=schema)
            except ValidationError as e:
                raise ConfigValidationError(
                    f"Invalid configuration for {plugin_id}: {e.message}"
                )

        # Cache
        self._cache[plugin_id] = config

        return config

    async def _load_user_config(self, plugin_id: str) -> dict[str, Any] | None:
        """Load user configuration file."""
        config_file = self.config_dir / "plugins" / f"{plugin_id}.yaml"

        if not config_file.exists():
            return None

        try:
            with config_file.open() as f:
                data = yaml.safe_load(f)
                return data.get("settings", {}) if data else {}
        except Exception as e:
            logger.warning(f"Failed to load config for {plugin_id}: {e}")
            return None

    def _load_env_config(self, plugin_id: str) -> dict[str, Any]:
        """Load configuration from environment variables.

        Supports: BERG_PLUGIN_<PLUGIN_ID>_<KEY>=value
        Nested keys: BERG_PLUGIN_<ID>_FEATURES__ISSUES=true
        """
        prefix = f"BERG_PLUGIN_{plugin_id.upper().replace('-', '_')}_"
        config = {}

        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue

            # Extract setting key
            setting_key = key[len(prefix):].lower()

            # Handle nested keys (FEATURES__ISSUES → features.issues)
            parts = setting_key.split("__")

            # Set value in nested dict
            current = config
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Parse value (basic type inference)
            current[parts[-1]] = self._parse_env_value(value)

        return config

    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value."""
        # Boolean
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False

        # Number
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # String
        return value

    def _expand_env_vars(self, config: Any) -> Any:
        """Recursively expand ${env:VAR} references."""
        if isinstance(config, str):

            def replace(match):
                """Replace environment variable references with their values.

                Returns the value of the environment variable or empty string if not found.

                :param match:
                :return:
                """
                var_name = match.group(1)
                return os.environ.get(var_name, "")

            return self._env_pattern.sub(replace, config)
        elif isinstance(config, dict):
            return {k: self._expand_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._expand_env_vars(item) for item in config]
        else:
            return config

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base (mutates base)."""
        for key, value in override.items():
            if (
                    key in base
                    and isinstance(base[key], dict)
                    and isinstance(value, dict)
            ):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def get(self, plugin_id: str) -> dict[str, Any] | None:
        """Get cached configuration."""
        return self._cache.get(plugin_id)

    async def reload(self, plugin_id: str) -> dict[str, Any]:
        """Reload configuration for a plugin."""
        # Clear cache
        self._cache.pop(plugin_id, None)

        # Reload
        # Would need access to plugin metadata here
        return await self.load_config(plugin_id)

    async def update(
            self, plugin_id: str, updates: dict[str, Any], persist: bool = True
    ) -> None:
        """Update plugin configuration.

        Args:
            plugin_id: Plugin ID
            updates: Configuration updates
            persist: Write to config file
        """
        # Get current config
        current = self._cache.get(plugin_id, {})

        # Merge updates
        self._deep_merge(current, updates)

        # Update cache
        self._cache[plugin_id] = current

        # Persist to file
        if persist:
            await self._save_user_config(plugin_id, current)

    async def _save_user_config(
            self, plugin_id: str, settings: dict[str, Any]
    ) -> None:
        """Save configuration to user config file."""
        config_file = self.config_dir / "plugins" / f"{plugin_id}.yaml"

        # Ensure directory exists
        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing file to preserve other fields
        existing = {}
        if config_file.exists():
            with config_file.open() as f:
                existing = yaml.safe_load(f) or {}

        # Update settings
        existing["settings"] = settings

        # Write back
        with config_file.open("w") as f:
            yaml.safe_dump(existing, f, default_flow_style=False)


# Runtime Configuration

# Dynamic Reconfiguration


class PluginConfigWatcher:
    """Watch for configuration changes and reload."""

    def __init__(
            self, config_manager: PluginConfigManager, lifecycle: PluginLifecycle
    ):
        self.config_manager = config_manager
        self.lifecycle = lifecycle
        self.watchers: dict[str, FileWatcher] = {}  # TODO: Implement FileWatcher class

    async def watch(self, plugin_id: str) -> None:
        """Watch plugin configuration for changes."""
        config_file = (
                self.config_manager.config_dir / "plugins" / f"{plugin_id}.yaml"
        )

        if not config_file.exists():
            return

        watcher = FileWatcher(config_file)  # TODO: Implement FileWatcher class
        watcher.on_change(lambda: self._on_config_change(plugin_id))
        self.watchers[plugin_id] = watcher
        await watcher.start()

    async def _on_config_change(self, plugin_id: str) -> None:
        """Handle configuration change."""
        logger.info(f"Configuration changed for {plugin_id}")

        try:
            # Reload config
            new_config = await self.config_manager.reload(plugin_id)

            # Notify plugin
            entry = self.lifecycle.registry.get(plugin_id)
            if entry and entry.instance:
                if hasattr(entry.instance, "on_config_change"):
                    context = await self.lifecycle._create_context(entry)
                    await entry.instance.on_config_change(context, new_config)
                    logger.info(f"Plugin {plugin_id} reconfigured")
                else:
                    logger.info(
                        f"Plugin {plugin_id} does not support live reconfiguration"
                    )
        except Exception as e:
            logger.error(f"Failed to reload config for {plugin_id}: {e}")
