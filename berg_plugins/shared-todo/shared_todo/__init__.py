"""Shared ToDo plugin package."""

# NOTE: Relative import so `import shared_todo` exposes the plugin class
# both from a checkout (plugin dir on sys.path) and installed dist.
from shared_todo.shared_todo import SharedToDoPlugin

# ----------------------------------------------------------------------
# Validation imports
# ----------------------------------------------------------------------
from shared_todo.shared_todo_config import (
    SharedTodoConfig,
    validate_shared_todo_config,
)
from shared_todo.shared_todo_distribution import (
    is_integrated_into_berg_agents,
    is_plugin_installable,
)
from shared_todo.shared_todo_user_cfg import validate_user_config


# ----------------------------------------------------------------------
__all__ = [
    "SharedToDoPlugin",
    "SharedTodoConfig",
    "is_integrated_into_berg_agents",
    "is_plugin_installable",
    "validate_shared_todo_config",
    "validate_user_config"]
