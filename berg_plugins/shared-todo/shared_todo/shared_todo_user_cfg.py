"""Verify that the user’s configuration (environment variables, config files, or CLI options) conforms to the expected schema and defaults.

**Key aspects**
- Check that required environment variables (e.g., `SH_TODO_ENABLED`, `SH_TODO_LOG_LEVEL`) are set.
- Validate that config file (e.g., `~/.shared_todo/config.yaml`) parses correctly.
- Ensure default fallbacks are applied when optional values are missing.
- Loads **.env** from the project root (via `python-dotenv`) so that environment variables defined there are available.

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

from pathlib import Path


# ----------------------------------------------------------------------
# Load environment variables from .env (if python-dotenv is installed)
# ----------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    # Load .env from the current working directory (usually the project root)
    load_dotenv()
except ImportError:
    # python-dotenv not installed – proceed without it; the user must
    # ensure the required vars are already in os.environ.
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Allow overriding the config file location via env var
CONFIG_PATH_ENV = os.getenv("SH_TODO_CONFIG_PATH")
DEFAULT_CONFIG_PATH = (
    Path(CONFIG_PATH_ENV)
    if CONFIG_PATH_ENV
    else PROJECT_ROOT / ".berg-agents" / ".shared_todo" / "config.yaml"
)
REQUIRED_ENV = {"SH_TODO_ENABLED": bool, "SH_TODO_LOG_LEVEL": str}


def load_user_config() -> dict:
    """Load user configuration from the default config file path, expanding environment variables.

    :return: A dictionary containing the user configuration, with environment variables expanded.
    """
    cfg_path = DEFAULT_CONFIG_PATH
    if cfg_path.is_file():
        with Path(cfg_path).open(encoding="utf-8") as f:
            import os
            import re

            import yaml

            def expand_env_vars(obj):
                """Expand environment variables in strings, dicts, and lists recursively.

                :param obj: The object to expand (str, dict, list, or other).
                :return: The object with environment variables expanded.
                """
                if isinstance(obj, str):
                    # Replace ${env:VAR} or ${VAR} with os.environ value or empty string if not set
                    def replace_match(match) -> str:
                        """Replace regex match with environment variable value.

                        :param match:  The regex match object.
                        :return:  The environment variable value or empty string if not set.
                        """
                        var_name = match.group(1) or match.group(2)
                        return os.getenv(var_name, "")

                    return re.sub(
                        r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}|\\$([A-Za-z_][A-Za-z0-9_]*)",
                        replace_match,
                        obj,
                    )
                elif isinstance(obj, dict):
                    return {k: expand_env_vars(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [expand_env_vars(item) for item in obj]
                else:
                    return obj

            raw_cfg = yaml.safe_load(f) or {}
            return expand_env_vars(raw_cfg)
    return {}


def validate_user_config() -> dict:
    """
    Combines environment variables and config file, then validates required keys.
    Returns a consolidated configuration dict.
    Raises ValueError if a required key is missing or malformed.
    """
    cfg = load_user_config()
    # env_cfg now contains vars that were either originally in os.environ
    # or loaded from .env by the early load_dotenv() call above.
    env_cfg = {k: v for k, v in os.environ.items() if k in REQUIRED_ENV}
    merged = {**cfg, **env_cfg}

    # Set defaults for optional keys before validation
    merged.setdefault(
        "SH_TODO_ENABLED", True
    )  # default to True if not provided
    merged.setdefault("SH_TODO_LOG_LEVEL", "INFO")  # default log level

    # Validate required keys (now guaranteed to exist because of setdefault)
    for key, expected_type in REQUIRED_ENV.items():
        value = merged[key]  # value is guaranteed to exist
        # ---- BOOL‑SPECIFIC HANDLING ----
        if expected_type is bool:
            # Accept common truthy strings and native bool values
            truthy = {"true", "1", "yes", "y", "on"}
            if isinstance(value, str):
                merged[key] = value.lower() in truthy
            else:
                # native bool (True/False) – keep as‑is
                merged[key] = bool(value)
        # For non bool types keep the original check
        elif not isinstance(value, expected_type):
            raise ValueError(
                f"Configuration '{key}' must be a {expected_type.__name__}"
            )

    # Optional: coerce types (adjusted)
    merged["SH_TODO_LOG_LEVEL"] = str(
        merged.get("SH_TODO_LOG_LEVEL", "INFO")
    ).upper()
    return merged


# Example usage removed for library import safety
# The validate_user_config function is available for external scripts;
# it will raise a ValueError if the configuration is invalid.
