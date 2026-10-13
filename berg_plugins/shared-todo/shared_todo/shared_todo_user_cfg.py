"""Verify that the user’s configuration (environment variables, config files, or CLI options) conforms to the expected schema and defaults.

**Key aspects**
- Check that required environment variables (e.g., `SH_TODO_ENABLED`, `SH_TODO_LOG_LEVEL`) are set.
- Validate that config file (e.g., `~/.shared_todo/config.yaml`) parses correctly.
- Ensure default fallbacks are applied when optional values are missing.

**Implementation (Python + YAML + env)**

# How to use it

from shared_todo_user_cfg import validate_user_cfg

try:
    cfg = validate_user_cfg()

    # cfg now contains SH_TODO_ENABLED, SH_TODO_LOG_LEVEL, plus any file‑based keys

    print("Ready to go – config:", cfg)
except ValueError as e:

    # Show the user a helpful error message and exit / fallback to defaults

    print("❌ Error:", e)
    raise SystemExit(str(e))
"""
import os
import yaml
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / ".shared_todo" / "config.yaml"
REQUIRED_ENV = {
    "SH_TODO_ENABLED": bool,
    "SH_TODO_LOG_LEVEL": str}


def load_user_config() -> dict:
    cfg_path = DEFAULT_CONFIG_PATH
    if cfg_path.is_file():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def validate_user_config() -> dict:
    """
    Combines environment variables and config file, then validates required keys.
    Returns a consolidated configuration dict.
    Raises ValueError if a required key is missing or malformed.
    """
    cfg = load_user_config()
    env_cfg = {k: v for k, v in os.environ.items() if k in REQUIRED_ENV}
    merged = {**cfg, **env_cfg}

    # Ensure required keys exist
    for key, expected_type in REQUIRED_ENV.items():
        if key not in merged:
            raise ValueError(f"Missing required configuration: {key}")
        if not isinstance(merged[key], expected_type):
            raise ValueError(f"Configuration '{key}' must be a {expected_type.__name__}")

    # Optional: coerce types
    merged["SH_TODO_ENABLED"] = bool(merged.get("SH_TODO_ENABLED", False))
    merged["SH_TODO_LOG_LEVEL"] = str(merged.get("SH_TODO_LOG_LEVEL", "INFO")).upper()
    return merged


# Example usage
try:
    final_cfg = validate_user_config()
    print("✅ User configuration is valid:", final_cfg)
except ValueError as e:
    print("❌ User configuration error:", e)
    raise SystemExit(str(e))