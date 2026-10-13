"""Determine the distribution mode: standalone installable plugin vs. direct integration into the berg‑agents package.

**Why it matters**
- **Standalone plugin**: Requires packaging (e.g., `setup.py`/`pyproject.toml`), versioning, and optional installation via `pip`.
- **Direct integration**: Lives inside `berg-agents`; imports may be relative and do not need separate distribution.

**Implementation suggestions**
- **Detect installed package**: Check if `importlib.util.find_spec("shared_todo_plugin")` succeeds.
- **Check for `setup.py` / `pyproject.toml`**: Presence indicates a distributable package.
- **Validate module import path**: Attempt `import berg_agents.shared_todo` and confirm it loads without error when integrated.


# How to use it

from shared_todo_distribution import is_plugin_installable, is_integrated_into_berg_agents

if is_plugin_installable():
    # e.g., show a “Install as plugin” UI entry
    pass
elif is_integrated_into_berg_agents():
    # e.g., import from berg_agents
    is_imported = "SharedToDoPlugin"
    from berg_agents import *
    import re
    if is_integrated_into_berg_agents():
        for name in dir():
            if re.search(is_imported, name):
                print(f"✅ {is_imported} is imported from berg_agents.")
                break

"""
import importlib.util


def is_plugin_installable() -> bool:
    """
    Returns True if a distributable package named 'shared_todo_plugin' can be found.
    """
    spec = importlib.util.find_spec("shared_todo_plugin")
    return spec is not None


def is_integrated_into_berg_agents() -> bool:
    """
    Returns True if the shared todo functionality is imported as part of berg_agents.
    """
    try:
        __import__("berg_agents.shared_todo")
        return True
    except ImportError:
        return False


# Example usage
if is_plugin_installable():
    print("🔌 Shared todo can be distributed as a standalone plugin.")
elif is_integrated_into_berg_agents():
    print("📦 Shared todo is integrated directly into berg_agents.")
else:
    print("⚠️  Unable to determine distribution mode.")

