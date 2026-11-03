# Plugin Configuration & Settings System

*Generated: 2026-10-10*

## Overview

The configuration system provides plugins with isolated, validated settings from multiple sources with environment variable expansion, schema validation, and runtime reconfiguration.

## Configuration Sources

Configuration is resolved from multiple sources in priority order:

```
1. Runtime overrides (highest priority)
2. User config (.berg-agents/plugins/<plugin-id>.yaml)
3. Environment variables (BERG_PLUGIN_<NAME>_<KEY>)
4. Plugin defaults (plugin.yaml in plugin package)
5. Schema defaults (lowest priority)
```

## Configuration Schema

### Schema Definition

Plugins define settings schemas using JSON Schema:

```yaml
# plugin.yaml
id: berg-plugin-github
version: 1.0.0

settings_schema:
  type: object
  properties:
    token:
      type: string
      description: "GitHub personal access token"
      secret: true
    org:
      type: string
      description: "GitHub organization"
      default: ""
    rate_limit:
      type: integer
      description: "API rate limit (requests per hour)"
      minimum: 100
      maximum: 5000
      default: 1000
    cache_ttl:
      type: integer
      description: "Cache TTL in seconds"
      default: 300
    features:
      type: object
      properties:
        issues:
          type: boolean
          default: true
        pull_requests:
          type: boolean
          default: true
        repositories:
          type: boolean
          default: false
  required:
    - token
```

### Pydantic Schema (Alternative)

For plugins written in Python, use Pydantic models:

```python
from pydantic import BaseModel, Field, SecretStr


class GithubSettings(BaseModel):
    """GitHub plugin settings."""

    token: SecretStr = Field(..., description="GitHub personal access token")
    org: str = Field(default="", description="GitHub organization")
    rate_limit: int = Field(
        default=1000,
        ge=100,
        le=5000,
        description="API rate limit (requests per hour)",
    )
    cache_ttl: int = Field(default=300, description="Cache TTL in seconds")

    class Config:
        # Convert to/from JSON schema
        json_schema_extra = {"required": ["token"]}
```

## User Configuration

### Plugin-Specific Config

```yaml
# .berg-agents/plugins/berg-plugin-github.yaml
enabled: true

settings:
  token: ${env:GITHUB_TOKEN}
  org: "my-organization"
  rate_limit: 2000
  cache_ttl: 600
  features:
    issues: true
    pull_requests: true
    repositories: true
```

### Environment Variables

Support both explicit and automatic env var expansion:

```bash
# Explicit expansion in .berg-agents
GITHUB_TOKEN=ghp_xxx

# Automatic env var mapping
BERG_PLUGIN_GITHUB_TOKEN=ghp_xxx
BERG_PLUGIN_GITHUB_ORG=my-org
BERG_PLUGIN_GITHUB_RATE_LIMIT=2000
```

## [Configuration Manager](../config/config_manager.py)

```python
import os
from pathlib import Path
import re
from typing import Any

from jsonschema import ValidationError, validate
import yaml


class PluginConfigManager:
    """Manage plugin configurations."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self._cache: dict[str, dict[str, Any]] = {}
        self._env_pattern = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")

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

        # Load from user .berg-agents file
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
            logger.warning(f"Failed to load .berg-agents for {plugin_id}: {e}")
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
            setting_key = key[len(prefix) :].lower()

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
        if value.lower() in {"true", "yes", "1"}:
            return True
        if value.lower() in {"false", "no", "0"}:
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
```

## Runtime Configuration

### [Dynamic Reconfiguration](../config/config_manager.py)

```python
class PluginConfigWatcher:
    """Watch for configuration changes and reload."""

    def __init__(
        self, config_manager: PluginConfigManager, lifecycle: PluginLifecycle
    ) -> None:
        self.config_manager = config_manager
        self.lifecycle = lifecycle
        self.watchers: dict[str, FileWatcher] = {}

    async def watch(self, plugin_id: str) -> None:
        """Watch plugin configuration for changes."""
        config_file = (
            self.config_manager.config_dir / "plugins" / f"{plugin_id}.yaml"
        )

        if not config_file.exists():
            return

        watcher = FileWatcher(config_file)
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
```

### Configuration Hook

```python
class BergPlugin(ABC):
    """Base plugin with configuration support."""

    async def on_config_change(
        self, context: PluginContext, new_config: dict[str, Any]
    ) -> None:
        """Called when configuration changes.

        Optional hook - implement to support live reconfiguration.
        """
```

## Secrets Management

### [Secret Detection](../config/secret_func.py)

```python
class SecretDetector:
    """Detect and protect secrets in configuration."""

    SECRET_PATTERNS = [
        r"token",
        r"api[_-]?key",
        r"password",
        r"secret",
        r"private[_-]?key",
        r"credential"]

    def is_secret_field(self, field_name: str) -> bool:
        """Check if field name suggests a secret."""
        field_lower = field_name.lower()
        return any(
            re.search(pattern, field_lower) for pattern in self.SECRET_PATTERNS
        )

    def mark_secrets(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Mark secret fields in schema."""
        if "properties" not in schema:
            return schema

        for field, field_schema in schema["properties"].items():
            if self.is_secret_field(field):
                field_schema["secret"] = True

        return schema
```

### [Secret Storage](../config/secret_func.py)

```python
from cryptography.fernet import Fernet


class SecretStore:
    """Encrypted storage for plugin secrets."""

    def __init__(self, key_file: Path) -> None:
        self.key_file = key_file
        self._cipher = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        """Load or create encryption key."""
        if self.key_file.exists():
            key = self.key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
            self.key_file.chmod(0o600)  # Owner read/write only

        return Fernet(key)

    def encrypt(self, value: str) -> str:
        """Encrypt a secret value."""
        encrypted = self._cipher.encrypt(value.encode())
        return encrypted.decode()

    def decrypt(self, encrypted_value: str) -> str:
        """Decrypt a secret value."""
        decrypted = self._cipher.decrypt(encrypted_value.encode())
        return decrypted.decode()

    async def store_secret(self, plugin_id: str, key: str, value: str) -> None:
        """Store an encrypted secret."""
        self.encrypt(value)
        # Store in secure location (e.g., keyring, vault)

    async def retrieve_secret(self, plugin_id: str, key: str) -> str | None:
        """Retrieve and decrypt a secret."""
        # Retrieve from secure location
        encrypted = None  # Placeholder
        if encrypted:
            return self.decrypt(encrypted)
        return None
```

## Configuration Validation

### [Custom Validators](../config/validators.py)

```python
from collections.abc import Callable


class ConfigValidator:
    """Custom configuration validators."""

    def __init__(self) -> None:
        self.validators: dict[str, Callable] = {}

    def register(self, name: str, validator: Callable) -> None:
        """Register a custom validator."""
        self.validators[name] = validator

    def validate(
        self, value: Any, validator_name: str, **kwargs
    ) -> tuple[bool, str | None]:
        """Validate value with custom validator.

        Returns:
            (is_valid, error_message)
        """
        if validator_name not in self.validators:
            return True, None

        try:
            self.validators[validator_name](value, **kwargs)
            return True, None
        except ValueError as e:
            return False, str(e)


# Built-in validators
def validate_url(value: str, **kwargs) -> None:
    """Validate URL format."""
    from urllib.parse import urlparse

    result = urlparse(value)
    if not all([result.scheme, result.netloc]):
        raise ValueError(f"Invalid URL: {value}")


def validate_path(value: str, must_exist: bool = False, **kwargs) -> None:
    """Validate file path."""
    path = Path(value)
    if must_exist and not path.exists():
        raise ValueError(f"Path does not exist: {value}")


def validate_regex(value: str, **kwargs) -> None:
    """Validate regex pattern."""
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")
```

## Configuration Profiles

Support multiple configuration profiles (dev, staging, prod):

```yaml
# .berg-agents/plugins/berg-plugin-github.yaml
profiles:
  dev:
    settings:
      token: ${env:GITHUB_TOKEN_DEV}
      rate_limit: 100
  
  staging:
    settings:
      token: ${env:GITHUB_TOKEN_STAGING}
      rate_limit: 500
  
  prod:
    settings:
      token: ${env:GITHUB_TOKEN_PROD}
      rate_limit: 5000

# Active profile
active_profile: dev
```

## CLI Commands

```bash
# View plugin configuration
$ berg-agents .berg-agents show <plugin-id>

# Edit plugin configuration
$ berg-agents .berg-agents edit <plugin-id>

# Set configuration value
$ berg-agents .berg-agents set <plugin-id> <key> <value>

# Validate configuration
$ berg-agents .berg-agents validate <plugin-id>

# List all plugin configurations
$ berg-agents .berg-agents list
```

## [Configuration Context](../plugin_contract.py)

```python
@dataclass
class PluginContext:
    """Plugin runtime context (includes configuration)."""

    # ... other fields ...

    # Settings
    settings: dict[str, Any]  # Plugin-specific settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        keys = key.split(".")
        value = self.settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def has_setting(self, key: str) -> bool:
        """Check if setting exists."""
        return self.get_setting(key) is not None
```

## Summary

**Configuration sources:** Runtime → User config → Environment → Plugin defaults → Schema defaults

**Key features:**
- JSON Schema validation
- Environment variable expansion
- Deep merge from multiple sources
- Secret detection and encryption
- Live reconfiguration
- Configuration profiles
- Custom validators

**Next:** Event system and inter-plugin communication
