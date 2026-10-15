# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Human-in-the-Loop approval system for plugin actions.

Integrates with berg_agents approval system when available.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HITLStatus(str, Enum):
    """HITL request status."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


@dataclass
class HITLRequest:
    """Human-in-the-loop approval request."""

    plugin_id: str
    action: str
    description: str
    risk_level: str
    context: dict[str, Any] = field(default_factory=dict)

    id: str = ""
    status: HITLStatus = HITLStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: datetime | None = None
    approver: str | None = None
    reason: str | None = None


class HITLManager:
    """Manage human-in-the-loop approval requests for plugins.

    Integrates with berg_agents approval system if available.
    """

    def __init__(self, app: Any = None) -> None:
        self.app = app
        self.requests: dict[str, HITLRequest] = {}
        self.pending: asyncio.Queue[HITLRequest] = asyncio.Queue()
        self._counter = 0

    async def request_approval(
        self,
        plugin_id: str,
        action: str,
        description: str,
        risk_level: str = "medium",
        context: dict[str, Any] | None = None,
        timeout: float = 300.0,
    ) -> bool:
        """Request approval for a plugin action.

        Auto-approves low-risk actions. For higher risk, integrates with
        berg_agents approval system if available, otherwise queues for manual approval.

        Args:
            plugin_id: Plugin requesting approval
            action: Action to perform
            description: Human-readable description
            risk_level: Risk level (low, medium, high, critical)
            context: Additional context
            timeout: Timeout in seconds

        Returns:
            True if approved, False if denied/timeout
        """
        # Auto-approve low-risk actions
        if risk_level == "low":
            logger.debug(f"Auto-approved low-risk: {action}")
            return True

        # Create request
        self._counter += 1
        request = HITLRequest(
            id=f"hitl_{self._counter}",
            plugin_id=plugin_id,
            action=action,
            description=description,
            risk_level=risk_level,
            context=context or {},
        )

        self.requests[request.id] = request

        # Try to use berg_agents approval if available
        if self.app and hasattr(self.app, "request_approval"):
            try:
                approved = await self.app.request_approval(
                    action=action,
                    description=description,
                    risk_level=risk_level,
                    context=context,
                    timeout=timeout,
                )
                request.status = (
                    HITLStatus.APPROVED if approved else HITLStatus.DENIED
                )
                request.resolved_at = datetime.now()
                return approved
            except Exception as e:
                logger.warning(f"berg_agents approval failed: {e}")

        # Fallback: queue for manual approval
        await self.pending.put(request)
        logger.info(
            f"Approval requested for {plugin_id}: {action} (risk: {risk_level})"
        )

        try:
            result = await asyncio.wait_for(
                self._wait_for_approval(request.id), timeout=timeout
            )
            return result
        except TimeoutError:
            logger.warning(f"Approval request {request.id} timed out")
            request.status = HITLStatus.TIMEOUT
            request.resolved_at = datetime.now()
            return False

    async def _wait_for_approval(self, request_id: str) -> bool:
        """Wait for approval decision."""
        while True:
            request = self.requests.get(request_id)
            if not request:
                return False
            if request.status == HITLStatus.APPROVED:
                return True
            elif request.status in (HITLStatus.DENIED, HITLStatus.TIMEOUT):
                return False
            await asyncio.sleep(0.1)

    def approve(
        self, request_id: str, approver: str = "user", reason: str = ""
    ) -> bool:
        """Approve a pending request."""
        request = self.requests.get(request_id)
        if not request or request.status != HITLStatus.PENDING:
            return False
        request.status = HITLStatus.APPROVED
        request.resolved_at = datetime.now()
        request.approver = approver
        request.reason = reason
        logger.info(f"Approved {request_id} by {approver}")
        return True

    def deny(
        self, request_id: str, approver: str = "user", reason: str = ""
    ) -> bool:
        """Deny a pending request."""
        request = self.requests.get(request_id)
        if not request or request.status != HITLStatus.PENDING:
            return False
        request.status = HITLStatus.DENIED
        request.resolved_at = datetime.now()
        request.approver = approver
        request.reason = reason
        logger.info(f"Denied {request_id} by {approver}")
        return True

    def get_pending_requests(self) -> list[HITLRequest]:
        """Get all pending approval requests."""
        return [
            r for r in self.requests.values() if r.status == HITLStatus.PENDING
        ]
