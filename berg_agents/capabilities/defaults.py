"""Default capability specs for FS, Shell, Memory."""

from __future__ import annotations

READ_ONLY_TOOL_NAMES = ["read-file", "search-explain"]
DENIED_COMMANDS = ["rm -rf /", "sudo"]
TIMEOUT = 30
MEMORY_STORE = "memory_store"
MEMORY_SEARCH = "memory_search"
