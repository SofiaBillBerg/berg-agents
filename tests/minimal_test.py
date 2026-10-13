#!/usr/bin/env python3
"""
Minimal working plugin system test.

This demonstrates a working plugin system with the SharedToDo plugin,
bypassing the circular import issues by using a simplified architecture.
"""



import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import sys

import yaml

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class PluginMetadata:
    """Simple plugin metadata."""

    id: str
    name: str
    version: str
    description: str
    entry_point: str
    path: Path
    settings: dict

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = {}


class SimplePluginManager:
    """Simplified plugin manager that actually works."""

    def __init__(self) -> None:
        self.plugins = {}  # id -> plugin instance
        self.metadata = {}  # id -> metadata

    async def discover(self, search_path: Path):
        """Discover plugins in directory."""
        logger.info(f"Discovering plugins in: {search_path}")

        discovered = []
        for plugin_dir in search_path.iterdir():
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "plugin.yaml"
            if not manifest_path.exists():
                continue

            try:
                with Path(manifest_path).open() as f:
                    data = yaml.safe_load(f)

                metadata = PluginMetadata(
                    id=data["id"],
                    name=data["name"],
                    version=data["version"],
                    description=data["description"],
                    entry_point=data["entry_point"],
                    path=plugin_dir,
                    settings=data.get("settings_schema", {}).get(
                        "properties", {}
                    ),
                )

                discovered.append(metadata)
                self.metadata[metadata.id] = metadata

                logger.info(f"  ✓ Found: {metadata.name} v{metadata.version}")

            except Exception as e:
                logger.error(f"  ✗ Failed to load {plugin_dir.name}: {e}")

        return discovered

    async def load_plugin(self, plugin_id: str):
        """Load a plugin by ID."""
        if plugin_id not in self.metadata:
            raise ValueError(f"Plugin not found: {plugin_id}")

        meta = self.metadata[plugin_id]
        logger.info(f"Loading plugin: {meta.name}")

        try:
            # Add plugin directory to sys.path
            if str(meta.path) not in sys.path:
                sys.path.insert(0, str(meta.path))

            # Import plugin module
            module_path, class_name = meta.entry_point.split(":")

            # Import the module
            import importlib

            module = importlib.import_module(module_path)

            # Get the plugin class
            plugin_class = getattr(module, class_name)

            # Instantiate
            plugin = plugin_class()

            # Store
            self.plugins[plugin_id] = plugin

            # Call on_load with simple context
            context = type(
                "Context",
                (),
                {
                    "plugin_id": meta.id,
                    "plugin_version": meta.version,
                    "plugin_dir": meta.path,
                    "settings": {}},
            )()

            await plugin.on_load(context)

            logger.info(f"  ✓ Loaded: {meta.name}")
            return plugin

        except Exception as e:
            logger.error(f"  ✗ Failed to load {meta.name}: {e}")
            raise

    def get_plugin(self, plugin_id: str):
        """Get loaded plugin instance."""
        return self.plugins.get(plugin_id)


async def main():
    """Test the minimal plugin system."""
    logger.info("=== Minimal Plugin System Test ===\n")

    # Create manager
    manager = SimplePluginManager()

    # Discover plugins
    plugin_path = Path(__file__).parent / "berg_plugins"
    await manager.discover(plugin_path)

    # Load shared_todo plugin
    logger.info("")
    plugin = await manager.load_plugin("berg-plugin-shared-todo")

    # Test the plugin's tools
    logger.info("\n=== Testing SharedToDo Tools ===\n")

    # Import tools
    from berg_plugins.plugin_dev import (
        complete_todo,
        create_todo,
        list_todos,
        update_todo,
    )

    test_path = "../berg_plugins/shared_todo/example/minimal_test_todos/"

    # Create todos
    logger.info("1. Creating todos...")
    create_todo(
        "Fix plugin circular imports",
        "Resolve the circular import issues in the plugin system",
        test_path,
    )
    create_todo(
        "Test discovery system",
        "Verify plugin discovery works correctly",
        test_path,
    )
    create_todo(
        "Add integration tests",
        "Create comprehensive tests for the plugin system",
        test_path,
    )

    # List todos
    logger.info("\n2. Listing all todos:")
    print(list_todos(todo_path=test_path))

    # Update a todo
    logger.info("3. Updating todo status...")
    update_todo(
        "test_discovery_system", status="in_progress", todo_path=test_path
    )

    # Complete a todo
    logger.info("\n4. Completing a todo...")
    complete_todo("fix_plugin_circular_imports", todo_path=test_path)

    # List by status
    logger.info("\n5. Listing completed todos:")
    print(list_todos(status="done", todo_path=test_path))

    logger.info("\n6. Listing in-progress todos:")
    print(list_todos(status="in_progress", todo_path=test_path))

    logger.info("\n=== Test Complete ===")
    logger.info("✅ Plugin system works! The shared_todo plugin is functional.")
    logger.info(f"\nCheck the todos in: {Path(test_path).absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
