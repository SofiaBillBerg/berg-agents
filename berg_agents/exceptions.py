"""Custom exception hierarchy for the berg_agents package.

All public functions raise :class:`CodeAgentError` (or a subclass) so
that callers can catch a single exception type.  This also allows the
CLI to catch all exceptions and print a user-friendly message.
"""


class CodeAgentError(RuntimeError):
    """Base exception for all berg_agents related errors."""


class FileCreationError(CodeAgentError):
    """Raised when a file cannot be created or written to."""


class InvalidToolError(CodeAgentError):
    """Raised when a tool name does not exist in the agent's tool set."""
