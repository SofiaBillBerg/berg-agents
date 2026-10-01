"""Capability layer - tool routing and catalog.

Only :class:`ToolCatalog` is actively used (by the harness routing layer).
The old capability-registry / envelope / audit / tool-adapter modules were
removed as dead code (no callers after the VercelAIAdapter rewrite).
"""

from __future__ import annotations

from .registry import ToolCatalog


__all__ = ["ToolCatalog"]
