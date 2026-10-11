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

## Security Wrappers
import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import httpx

from berg_agents.capabilities.base import RiskClass, RISK_HIGH
from feat_dev.plugin_dev.plugin_system.permissions.permissions import PermissionChecker, PermissionCategory
from feat_dev.plugin_dev.plugin_system.permissions.sandbox import SandboxLevel

logger = logging.getLogger(__name__)


### Filesystem Wrapper


class SecureFilesystem:
    """Filesystem operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker):
        self.plugin_id = plugin_id
        self.checker = checker

    async def read_file(self, path: str) -> str:
        """Read file with permission check."""
        if not await self.checker.check(
                self.plugin_id,
                PermissionCategory.FILESYSTEM_READ,
                target=path
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied read access to {path}"
            )

        # Audit log
        await self._audit("read_file", {"path": path})

        # Perform operation
        return Path(path).read_text()

    async def write_file(self, path: str, content: str) -> None:
        """Write file with permission check."""
        if not await self.checker.check(
                self.plugin_id,
                PermissionCategory.FILESYSTEM_WRITE,
                target=path
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied write access to {path}"
            )

        # Audit log
        await self._audit("write_file", {"path": path, "size": len(content)})

        # Perform operation
        Path(path).write_text(content)

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")


### Network Wrapper


class SecureNetwork:
    """Network operations with permission checking."""

    def __init__(self, plugin_id: str, checker: PermissionChecker):
        self.plugin_id = plugin_id
        self.checker = checker

    async def request(
            self,
            method: str,
            url: str,
            **kwargs
    ) -> httpx.Response:
        """HTTP request with permission check."""
        if not await self.checker.check(
                self.plugin_id,
                PermissionCategory.NETWORK_OUTBOUND,
                target=url
        ):
            raise PermissionDeniedError(
                f"Plugin {self.plugin_id} denied network access to {url}"
            )

        # Audit log
        await self._audit("http_request", {
            "method": method,
            "url": url
        })

        # Perform operation
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, **kwargs)

    async def _audit(self, operation: str, details: dict[str, Any]) -> None:
        """Write to audit log."""
        logger.info(f"[AUDIT] Plugin {self.plugin_id}: {operation} {details}")


## Audit System


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

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self._lock = asyncio.Lock()

    async def log(self, entry: AuditEntry) -> None:
        """Write audit entry."""
        async with self._lock:
            with self.log_file.open("a") as f:
                f.write(json.dumps(asdict(entry), default=str) + "\n")

    async def query(
            self,
            plugin_id: str | None = None,
            operation: str | None = None,
            since: datetime | None = None,
            limit: int = 100
    ) -> list[AuditEntry]:
        """Query audit log."""
        entries = []

        with self.log_file.open("r") as f:
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


## HITL Integration


class PluginHITL:
    """Human-in-the-loop approval for plugins."""

    def __init__(self, hitl_manager: HITLManager):
        self.hitl_manager = hitl_manager

    async def request_approval(
            self,
            plugin_id: str,
            operation: str,
            details: dict[str, Any],
            risk_level: RiskClass = RISK_HIGH
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
        request = HITLRequest(
            agent="plugin_system",
            tool=operation,
            args=details,
            risk_level=risk_level,
            context={
                "plugin_id": plugin_id,
                "timestamp": datetime.now().isoformat()
            }
        )

        # Show to user and wait for approval
        approved = await self.hitl_manager.request_approval(request)

        # Audit
        logger.info(
            f"[HITL] Plugin {plugin_id} {operation}: "
            f"{'approved' if approved else 'denied'}"
        )

        return approved


## Trust Levels


class TrustLevel(str, Enum):
    """Plugin trust levels."""

    UNTRUSTED = "untrusted"  # Unknown source, full sandboxing
    COMMUNITY = "community"  # Community plugin, process sandbox
    VERIFIED = "verified"  # Verified by berg_agents team
    BUILTIN = "builtin"  # Shipped with berg_agents


class TrustManager:
    """Manage plugin trust levels."""

    def __init__(self):
        self.trust_levels: dict[str, TrustLevel] = {}

    def get_trust_level(self, plugin_id: str) -> TrustLevel:
        """Get plugin trust level."""
        return self.trust_levels.get(plugin_id, TrustLevel.UNTRUSTED)

    def get_sandbox_level(self, trust: TrustLevel) -> SandboxLevel:
        """Determine sandbox level from trust."""
        if trust == TrustLevel.BUILTIN:
            return SandboxLevel.NONE
        elif trust == TrustLevel.VERIFIED:
            return SandboxLevel.NONE
        elif trust == TrustLevel.COMMUNITY:
            return SandboxLevel.PROCESS
        else:
            return SandboxLevel.CONTAINER
