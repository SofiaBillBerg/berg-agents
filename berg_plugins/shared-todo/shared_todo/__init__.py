"""Shared ToDo plugin package."""

# NOTE: Relative import so `import shared_todo` exposes the plugin class
# both from a checkout (plugin dir on sys.path) and installed dist.
from shared_todo.shared_todo import SharedToDoPlugin

# ----------------------------------------------------------------------
# Validation imports
# ----------------------------------------------------------------------
from shared_todo.shared_todo_config import validate_shared_todo_config, SharedTodoConfig
from shared_todo.shared_todo_distribution import is_plugin_installable, is_integrated_into_berg_agents
from shared_todo.shared_todo_user_cfg import validate_user_config

# ----------------------------------------------------------------------
__all__ = ["SharedToDoPlugin", "validate_shared_todo_config", "SharedTodoConfig", "is_plugin_installable", "is_integrated_into_berg_agents", "validate_user_config"]
