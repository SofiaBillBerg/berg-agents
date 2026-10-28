"""Quick sanity-check script."""

from shared_todo import (
    is_integrated_into_berg_agents,
    is_plugin_installable,
    validate_shared_todo_config,
    validate_user_config,
)


# 1️ Validate a minimal config
cfg = validate_shared_todo_config({
    "plugin_id": "shared_todo",
    "enabled": True,
    "log_level": "INFO"})
print("✅ Config model ok:", cfg)

# 2️ Detect distribution mode (will just log – no raise)
print("Installable?", is_plugin_installable())
print("Integrated?", is_integrated_into_berg_agents())

# 3 Validate user env/config file
try:
    u_cfg = validate_user_config()
    print("✅ User config ok:", u_cfg)
except ValueError as e:
    print("❌ User config problem:", e)
