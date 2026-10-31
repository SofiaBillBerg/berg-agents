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

"""Security wrappers for plugin operations."""

# Security Wrappers
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import Any, Literal

from berg_agents.capabilities.base import RISK_HIGH, RiskClass
import httpx
from plugin_system.exceptions import PermissionDeniedError
from plugin_system.permissions import HITLManager, HITLRequest
from plugin_system.permissions.permissions import (
    PermissionCategory,
    PermissionChecker,
)
from plugin_system.permissions.sandbox import SandboxLevel

logger = logging.getLogger(__name__)


# Filesystem Wrapper


class SecureFilesystem:
    """Filesystem operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker) -> None:
        self.plugin_id = plugin_id
        self.checker = checker

    async def read_file(self, path: str) -> str:
        """Read file with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.FILESYSTEM_READ, target=path
        ):
            raise PermissionDeniedError(  # TODO: Define PermissionDeniedError
                f"Plugin {self.plugin_id} denied read access to {path}"
            )

        # Audit log
        await self._audit("read_file", {"path": path})

        # Perform operation
        return Path(path).read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        """Write file with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.FILESYSTEM_WRITE, target=path
        ):
            raise PermissionDeniedError(  # TODO: Define PermissionDeniedError
                f"Plugin {self.plugin_id} denied write access to {path}"
            )

        # Audit log
        await self._audit("write_file", {"path": path, "size": len(content)})

        # Perform operation
        Path(path).write_text(content, encoding="utf-8")

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")


# Network Wrapper


class SecureNetwork:
    """Network operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker) -> None:
        self.plugin_id = plugin_id
        self.checker = checker

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """HTTP request with permission check."""
        if not await self.checker.check(
            self.plugin_id, PermissionCategory.NETWORK_OUTBOUND, target=url
        ):
            raise PermissionDeniedError(  # TODO: Define PermissionDeniedError
                f"Plugin {self.plugin_id} denied network access to {url}"
            )

        # Audit log
        await self._audit("http_request", {"method": method, "url": url})

        # Perform operation
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, **kwargs)

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")


# Audit System


@dataclass
class AuditEntry:
    """Audit log entry."""

    timestamp: datetime
    plugin_id: str
    operation: str
    details: dict[str, Any]
    result: Literal["success", "denied", "error"]
    user_approved: bool = False


class AuditLogger:
    """Audit log for plugin actions."""

    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file
        self._lock = asyncio.Lock()

    async def log(self, entry: AuditEntry) -> None:
        """Write audit entry."""
        async with self._lock:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), default=str) + "\n")

    async def query(
        self,
        plugin_id: str | None = None,
        operation: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit log."""
        entries = []

        with self.log_file.open("r", encoding="utf-8") as f:
            for line in f:
                entry_dict = json.loads(line)
                entry = AuditEntry(**entry_dict)

                # Apply filters
                if plugin_id and entry.plugin_id != plugin_id:
                    continue
                if operation and entry.operation != operation:
                    continue
                if since and entry.timestamp < since:
                    continue

                entries.append(entry)

                if len(entries) >= limit:
                    break

        return entries


# HITL Integration


class PluginHITL:
    """Human-in-the-loop approval for plugins."""

    def __init__(
        self, hitl_manager: HITLManager
    ) -> None:  # TODO: Define HITLRequest class
        """Initialize with HITL manager."""
        self.hitl_manager = hitl_manager

    async def request_approval(
        self,
        plugin_id: str,
        operation: str,
        details: dict[str, Any],
        risk_level: RiskClass = RISK_HIGH,
    ) -> bool:
        """Request user approval for operation.

        Args:
            plugin_id: Plugin requesting approval
            operation: Operation to perform
            details: Operation details
            risk_level: Risk classification

        Returns:
            True if approved
        """
        # Build approval request
        request = HITLRequest(  # TODO: Define HITLRequest class
            agent="plugin_system",
            tool=operation,
            args=details,
            risk_level=risk_level,
            context={
                "plugin_id": plugin_id,
                "timestamp": datetime.now().isoformat()},
        )

        # Show to user and wait for approval
        approved = await self.hitl_manager.request_approval(request)

        # Audit
        logger.info(
            f"[HITL] Plugin {plugin_id} {operation}: "
            f"{'approved' if approved else 'denied'}"
        )

        return approved


# Trust Levels


class TrustLevel(StrEnum):
    """Plugin trust levels."""

    UNTRUSTED = "untrusted"  # Unknown source, full sandboxing
    COMMUNITY = "community"  # Community plugin, process sandbox
    VERIFIED = "verified"  # Verified by berg_agents team
    BUILTIN = "builtin"  # Shipped with berg_agents


class TrustManager:
    """Manage plugin trust levels."""

    def __init__(self) -> None:
        self.trust_levels: dict[str, TrustLevel] = {}

    def get_trust_level(self, plugin_id: str) -> TrustLevel:
        """Get plugin trust level."""
        return self.trust_levels.get(plugin_id, TrustLevel.UNTRUSTED)

    def get_sandbox_level(self, trust: TrustLevel) -> SandboxLevel:
        """Determine sandbox level from trust."""
        if trust in {TrustLevel.BUILTIN, TrustLevel.VERIFIED}:
            return SandboxLevel.NONE
        elif trust == TrustLevel.COMMUNITY:
            return SandboxLevel.PROCESS
        else:
            return SandboxLevel.CONTAINER
