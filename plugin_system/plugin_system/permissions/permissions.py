# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

# Permission Categories
# Permission System
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Any

from plugin_system.discovery.plugin_registry import PluginRegistry

logger = logging.getLogger(__name__)


class PermissionCategory(StrEnum):
    """Plugin permission categories."""

    # Filesystem
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    FILESYSTEM_DELETE = "filesystem:delete"

    # Network
    NETWORK_OUTBOUND = "network:outbound"
    NETWORK_INBOUND = "network:inbound"

    # Environment
    ENV_READ = "env:read"
    ENV_WRITE = "env:write"

    # Process
    SUBPROCESS_SPAWN = "subprocess:spawn"
    SUBPROCESS_KILL = "subprocess:kill"

    # System
    SYSTEM_INFO = "system:info"
    SYSTEM_ADMIN = "system:admin"

    # Berg Agents
    AGENT_INVOKE = "agent:invoke"
    AGENT_MODIFY = "agent:modify"
    TOOL_REGISTER = "tool:register"
    TOOL_INVOKE = "tool:invoke"

    # Data
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    SECRETS_READ = "secrets:read"


# Permission Specification


@dataclass
class Permission:
    """Plugin permission specification."""

    category: PermissionCategory
    scope: dict[str, Any] | None = None

    def allows(self, action: str, target: str | None = None) -> bool:
        """Check if permission allows an action."""
        # No scope = allow all
        if not self.scope:
            return True

        # Check scope-specific rules
        if self.category == PermissionCategory.FILESYSTEM_READ:
            return self._check_path_scope(target, self.scope.get("paths", []))
        elif self.category == PermissionCategory.NETWORK_OUTBOUND:
            return self._check_domain_scope(
                target, self.scope.get("domains", [])
            )
        elif self.category == PermissionCategory.ENV_READ:
            return target in self.scope.get("vars", [])
        elif self.category == PermissionCategory.SUBPROCESS_SPAWN:
            return target in self.scope.get("commands", [])

        return False

    def _check_path_scope(self, path: str, allowed_patterns: list[str]) -> bool:
        """Check if path matches allowed patterns."""
        import fnmatch
        from pathlib import Path

        path_obj = Path(path)
        return any(
            fnmatch.fnmatch(str(path_obj), pattern)
            for pattern in allowed_patterns
        )

    def _check_domain_scope(self, url: str, allowed_domains: list[str]) -> bool:
        """Check if URL domain is allowed."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        for allowed in allowed_domains:
            if domain == allowed or domain.endswith(f".{allowed}"):
                return True
        return False


# Permission Checker


class PermissionChecker:
    """Check plugin permissions at runtime."""

    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry
        self.granted: dict[str, set[Permission]] = {}

    async def check(
        self,
        plugin_id: str,
        permission: PermissionCategory,
        target: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Check if plugin has permission.

        Args:
            plugin_id: Plugin requesting permission
            permission: Permission category
            target: Specific target (file path, URL, etc.)
            context: Additional context

        Returns:
            True if permission granted
        """
        entry = self.registry.get(plugin_id)
        if not entry:
            logger.exception(
                f"Permission check for unknown plugin: {plugin_id}"
            )
            return False

        # Check if permission was declared
        declared = any(
            p.category == permission for p in entry.metadata.permissions
        )

        if not declared:
            logger.warning(
                f"Plugin {plugin_id} requested undeclared permission: {permission}"
            )
            return False

        # Check if permission was granted
        if plugin_id not in self.granted:
            # First request - prompt user
            granted = await self._request_permission(
                plugin_id, permission, target, context
            )
            if granted:
                if plugin_id not in self.granted:
                    self.granted[plugin_id] = set()
                self.granted[plugin_id].add(
                    Permission(category=permission, scope=context)
                )
            return granted

        # Check granted permissions
        for perm in self.granted.get(plugin_id, set()):
            if perm.category == permission and perm.allows("", target):
                return True

        return False

    async def _request_permission(
        self,
        plugin_id: str,
        permission: PermissionCategory,
        target: str | None,
        context: dict[str, Any] | None,
    ) -> bool:
        """Request permission from user (HITL)."""
        # Build prompt
        prompt = f"Plugin '{plugin_id}' requests permission: {permission}"
        if target:
            prompt += f"\nTarget: {target}"
        if context:
            prompt += f"\nContext: {context}"

        # Show to user (would integrate with HITL system)
        # For now, just log
        logger.info(f"Permission request: {prompt}")

        # In real implementation, this would show a UI dialog
        # and wait for user approval
        return True  # Auto-approve for now
