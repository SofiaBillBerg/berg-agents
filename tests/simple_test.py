#!/usr/bin/env python3
"""
Simple test of plugin discovery and shared_todo functionality.
"""



import asyncio
import logging
from pathlib import Path
import sys

import pytest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@pytest.fixture
def test_env() -> dict[str, str]:
    return {
        "PLUGIN_PATH": str(Path(__file__).parent.parent / "berg_plugins"),
        "TODO_PATH": "./test_todos/"}


async def test_discovery():
    """Test plugin discovery directly."""
    logger.info("=== Testing Plugin Discovery ===")

    # Add the plugin_system directory to path
    sys.path.insert(0, str(Path(__file__).parent / "plugin_system"))

    try:
        # Import just the discovery module
        from berg_agents.plugin_system.discovery.discovery_process import (
            PluginDiscovery,
        )

        logger.info("Creating PluginDiscovery...")
        discovery = PluginDiscovery()

        # Discover plugins
        plugin_path = Path(__file__).parent / "berg_plugins"
        logger.info(f"Searching in: {plugin_path}")

        discovered = await discovery.discover_all([plugin_path])

        logger.info(f"Discovered {len(discovered)} plugins")
        for meta in discovered:
            logger.info(f"  - {meta.name} ({meta.id}) v{meta.version}")
            logger.info(f"    Entry point: {meta.entry_point}")
            logger.info(f"    Path: {meta.path}")

        return discovered

    except Exception as e:
        logger.error(f"Discovery test failed: {e}", exc_info=True)
        return []


async def test_shared_todo_standalone():
    """Test shared_todo tools directly, without the plugin system."""
    logger.info("\n=== Testing SharedToDo Tools ===")

    try:
        # Test the tools directly
        sys.path.insert(0, str(Path(__file__).parent))

        from berg_plugins.plugin_dev import (
            complete_todo,
            create_todo,
            list_todos,
        )

        # Create a test todo
        logger.info("Creating test todo...")
        result = create_todo(
            title="Test Standalone Tools",
            description="Testing the shared todo tools directly",
            todo_path="../berg_plugins/shared_todo/example/test_standalone_todos/",
        )
        logger.info(f"Result: {result}")

        # List todos
        logger.info("\nListing todos...")
        todos = list_todos(todo_path="../berg_plugins/shared_todo/example/test_standalone_todos/")
        logger.info(f"\n{todos}")

        # Complete the todo
        logger.info("\nCompleting todo...")
        result = complete_todo(
            "test_standalone_tools", todo_path="../berg_plugins/shared_todo/example/test_standalone_todos/"
        )
        logger.info(f"Result: {result}")

        # List completed todos
        logger.info("\nListing completed todos...")
        todos = list_todos(status="done", todo_path="../berg_plugins/shared_todo/example/test_standalone_todos/")
        logger.info(f"\n{todos}")

        logger.info("\n✓ SharedToDo tools work correctly!")

    except Exception as e:
        logger.error(f"SharedToDo test failed: {e}", exc_info=True)


async def test_plugin_yaml_parsing():
    """Test that plugin.yaml can be parsed correctly."""
    logger.info("\n=== Testing Plugin YAML Parsing ===")

    try:
        import yaml

        # Parse the shared_todo plugin.yaml
        yaml_path = (
            Path(__file__).parent
            / "berg_plugins"
            / "shared_todo"
            / "plugin.yaml"
        )

        logger.info(f"Loading: {yaml_path}")

        with Path(yaml_path).open() as f:
            data = yaml.safe_load(f)

        logger.info("Plugin YAML data:")
        logger.info(f"  ID: {data.get('id')}")
        logger.info(f"  Name: {data.get('name')}")
        logger.info(f"  Version: {data.get('version')}")
        logger.info(f"  Entry Point: {data.get('entry_point')}")
        logger.info(f"  Dependencies: {len(data.get('dependencies', []))}")

        if data.get("capabilities"):
            for cap in data.get("capabilities", []):
                logger.info(
                    f"  Capability: {cap.get('type')} - {cap.get('id')}"
                )

        logger.info("\n✓ Plugin YAML parsed successfully!")

    except Exception as e:
        logger.error(f"YAML parsing failed: {e}", exc_info=True)


async def main():
    """Run all tests."""
    logger.info("=== Simple Plugin System Test ===")

    # Test discovery
    await test_discovery()

    # Test YAML parsing
    await test_plugin_yaml_parsing()

    # Test shared_todo tools
    await test_shared_todo_standalone()

    logger.info("\n=== All Tests Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
