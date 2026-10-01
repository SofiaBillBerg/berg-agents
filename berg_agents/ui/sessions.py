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
        root_dir: str = ".",
    ) -> None:
        """Initialize session state.

        :param active_provider: Initially selected provider name.
        :param active_model: Initially selected model identifier.
        :param root_dir: Workspace root directory for file tools.
        """
        self.active_provider = active_provider
        self.active_model = active_model
        self._root_dir = root_dir

    def _harness_root_dir(self) -> str:
        """Return the workspace root directory for file tools.

        :return: Root directory path string.
        """
        return self._root_dir
