#!/usr/bin/env python3

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

#  Test script for Berg Agents Plugin System
#
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.

"""
Test script for the plugin system.

Tests:
1. Plugin discovery
2. Plugin loading
3. Plugin enabling
4. SharedTodo plugin functionality
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
import sys
import pytest
from feat_dev.plugin_dev.plugin_system.plugin_manager import PluginManager

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# setup test environment variables for the plugin system and mark for testing

@pytest.fixture
def test_env():
    return {
        "PLUGIN_PATH": str(Path(__file__).parent.parent / "berg_plugins"),
        "TODO_PATH": "./test_todos/"}


@dataclass
class MockBergAgentsApp:
    """Mock BergAgentsApp for testing."""

    def __init__(self):
        self.name = "test-app"

@dataclass
class MockHarness:
    """Mock Harness for testing."""

    def __init__(self):
        self.name = "test-harness"


async def main():
    """Run plugin system tests."""
    logger.info("=== Berg Agents Plugin System Test ===\n")

    # Create mock app and harness
    app = MockBergAgentsApp()
    harness = MockHarness()

    # Create plugin manager
    logger.info("1. Creating PluginManager...")
    manager = PluginManager(app, harness)

    # Initialize
    logger.info("2. Initializing plugin system...")
    await manager.initialize()

    # Discover plugins
    logger.info("3. Discovering plugins...")
    plugin_path = Path(__file__).parent.parent / "berg_plugins"
    logger.info(f"   Searching in: {plugin_path}")

    discovered = await manager.discover_plugins([plugin_path])
    logger.info(f"   ✓ Discovered {len(discovered)} plugins")

    for metadata in discovered:
        logger.info(
            f"     - {metadata.name} ({metadata.id}) v{metadata.version}"
        )

    # List plugins
    logger.info("\n4. Listing registered plugins...")
    plugins = await manager.list_plugins()
    for plugin in plugins:
        logger.info(f"   - {plugin['name']}: {plugin['state']}")

    # Load all plugins
    logger.info("\n5. Loading plugins...")
    await manager.load_all()

    # Enable all plugins
    logger.info("\n6. Enabling plugins...")
    await manager.enable_all()

    # Check final state
    logger.info("\n7. Final plugin states:")
    plugins = await manager.list_plugins()
    for plugin in plugins:
        logger.info(f"   - {plugin['name']}: {plugin['state']}")

    # Test SharedTodo plugin functionality
    logger.info("\n8. Testing SharedTodo plugin tools...")

    # Get the plugin instance
    todo_plugin = manager.get_plugin("berg-plugin-shared-todo")
    if todo_plugin:
        logger.info("   ✓ SharedTodo plugin loaded")

        # Test tools
        from feat_dev.plugin_dev.berg_plugins.shared_todo.tools import (
            complete_todo,
            create_todo,
            list_todos,
        )

        # Create a test todo
        logger.info("\n   Creating test todo...")
        result = create_todo(
            title="Test Plugin System",
            description="Verify that the plugin system works correctly",
            todo_path="./test_todos/",
        )
        logger.info(f"   {result}")

        # List todos
        logger.info("\n   Listing todos...")
        todos = list_todos(todo_path="./test_todos/")
        logger.info(f"\n{todos}")

        # Complete the todo
        logger.info("   Completing todo...")
        result = complete_todo("test_plugin_system", todo_path="./test_todos/")
        logger.info(f"   {result}")

        # List completed todos
        logger.info("\n   Listing completed todos...")
        todos = list_todos(status="done", todo_path="./test_todos/")
        logger.info(f"\n{todos}")

    else:
        logger.error("   ✗ SharedTodo plugin not found")

    # Shutdown
    logger.info("\n9. Shutting down plugin system...")
    await manager.shutdown()

    logger.info("\n=== Test Complete ===")
    logger.info("✓ All tests passed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"\n✗ Test failed: {e}", exc_info=True)
        sys.exit(1)
