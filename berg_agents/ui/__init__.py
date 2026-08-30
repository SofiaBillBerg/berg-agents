"""UI layer: rich terminal interface for the capability layer.

Exposes the public names of the rich CLI UI - the rendering helpers and the
interactive ``run_cli_ui`` session driver.
"""

from __future__ import annotations

from .cli_ui import (
    render_catalog,
    render_progress,
    render_receipt,
    render_request,
    render_response,
    run_cli_ui,
)

__all__ = [
    "render_catalog",
    "render_progress",
    "render_receipt",
    "render_request",
    "render_response",
    "run_cli_ui",
]
