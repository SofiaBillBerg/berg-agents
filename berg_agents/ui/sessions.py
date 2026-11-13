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

"""In-memory session state for the FastAPI layer.

Holds the active provider/model selection and workspace root directory.
The single :class:`SessionManager` instance lives on ``app.state`` (see
:mod:`berg_agents.ui.server`) so routes stay thin and testable through
dependency injection - no module-level singletons.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """Session-scoped state for the chat endpoint.

    The old SSE-thread / HITL / background-task machinery was removed
    when the chat endpoint migrated to ``VercelAIAdapter``. Only the
    active provider selection and root directory remain.
    """

    def __init__(
        self,
        *,
        active_provider: str = "ollama",
        active_model: str = "",
        active_agent: str | None = None,
        delegate_model: str = "",
        root_dir: str = ".",
    ) -> None:
        """Initialize session state.

        :param active_provider: Initially selected provider name.
        :param active_model: Initially selected model identifier.
        :param active_agent: Initially selected agent (None = default chat agent).
        :param delegate_model: Model delegated sub-agents run on. Empty means
            the tier default from configuration, which is what a delegated run
            resolved to before the choice existed.
        :param root_dir: Workspace root directory for file tools.
        """
        self.active_provider = active_provider
        self.active_model = active_model
        self.active_agent = active_agent
        # Kept separate from ``active_model`` on purpose: the chat brain's model
        # and a specialist's model are different choices. Sharing one field made
        # the specialist's model an invisible side effect of editing the chat
        # selector, which is not a choice anyone can see.
        self.delegate_model = delegate_model
        self._root_dir = root_dir

    def _harness_root_dir(self) -> str:
        """Return the workspace root directory for file tools.

        :return: Root directory path string.
        """
        return self._root_dir
