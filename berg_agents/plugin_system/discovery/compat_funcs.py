#  Berg Agents Plugin System - Compatibility Functions
#
"""
Compatibility functions for MCP toolsets and skill parsing.

Integrates with berg_agents per migration guide - wraps existing Skills and MCP
as plugins for resource efficiency (deferred loading).
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_skill(skill_path: Path) -> Any:
    """Parse a skill file into plugin metadata.

    Wraps existing berg_agents skills as deferred-load plugins.
    More resource efficient than loading all skills upfront.

    Args:
        skill_path: Path to skill file or directory

    Returns:
        Skill metadata wrapped as plugin or None if parsing fails
    """
    try:
        # Use berg_agents skill loader
        # Check if load_skill exists in berg_agents
        try:
            from berg_agents.capabilities.base import load_skill

            skill = load_skill(skill_path)
        except (ImportError, AttributeError):
            # Fallback: read skill file directly
            logger.debug("load_skill not available, reading file directly")
            skill = {
                "path": str(skill_path),
                "content": (
                    skill_path.read_text() if skill_path.exists() else ""
                )}
        logger.info(f"Parsed skill as plugin: {skill_path}")

        # Return wrapped as deferred plugin
        return {
            "type": "skill",
            "path": skill_path,
            "skill": skill,
            "deferred": True,  # Load only when needed
        }

    except ImportError:
        logger.debug("berg_agents not available for skill parsing")
        return None
    except Exception as e:
        logger.error(f"Failed to parse skill {skill_path}: {e}")
        return None


def create_mcp_toolset(mcp_spec: dict[str, Any]) -> Any:
    """Create an MCP toolset from specification.

    Wraps existing berg_agents MCP as deferred plugin.
    Connection established only when plugin is enabled (resource efficient).

    Args:
        mcp_spec: MCP toolset specification

    Returns:
        MCP toolset wrapped as plugin or None if creation fails
    """
    try:
        # Return wrapped spec for deferred connection
        logger.info(
            f"Created MCP plugin wrapper: {mcp_spec.get('name', 'unknown')}"
        )

        return {
            "type": "mcp",
            "spec": mcp_spec,
            "name": mcp_spec.get("name"),
            "server_url": mcp_spec.get("server_url") or mcp_spec.get("url"),
            "deferred": True,  # Connect only when enabled
        }

    except Exception as e:
        logger.error(f"Failed to create MCP toolset: {e}")
        return None
