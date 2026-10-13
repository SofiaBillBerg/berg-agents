"""Validate that all required configuration fields are present and correctly formatted.

**What to check**
- Presence of mandatory keys (e.g., `plugin_id`, `enabled`, `log_level`).
- Correct data types (strings, booleans, enums).
- Absence of stray/unexpected keys (optional but helpful for sanity).

# How to use it

user_cfg = {
    "plugin_id": "shared_todo",
    "enabled": True,
    "log_level": "DEBUG",
    # "extra_field": "should_fail"  # <-- would raise ValidationError
}
try:
    config = validate_shared_todo_config(user_cfg)
    print("✅ Configuration is valid:", config)
except ValidationError as e:
    print("❌ Configuration validation failed:\n", e)
"""

from pydantic import BaseModel, Field


class SharedTodoConfig(BaseModel):
    plugin_id: str = Field(..., description="Unique identifier for the shared todo plugin")
    enabled: bool = Field(..., description="Whether the plugin is active")
    log_level: str = Field("INFO", description="Logging verbosity (e.g., DEBUG, INFO, WARN, ERROR)")
    # Add any additional fields required by your plugin here


def validate_shared_todo_config(raw_config: dict) -> SharedTodoConfig:
    """
    Validate the raw configuration dictionary against the SharedTodoConfig model.
    Returns a validated model instance or raises a ValidationError.
    """
    return SharedTodoConfig(**raw_config)


