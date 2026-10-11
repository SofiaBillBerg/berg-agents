"""UI layer: rich terminal interface for the harness layer.

Exposes the public names of the rich harness TUI - the rendering helpers
and the interactive ``run_cli_ui`` session driver.
"""

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

from __future__ import annotations

from .cli_ui import (
    SLASH_COMMANDS,
    render_agents,
    render_help,
    render_history,
    render_result,
    render_stats,
    run_cli_ui,
    run_harness_task,
    run_tui,
)
from .server import create_app
from .sessions import SessionManager


__all__ = [
    "SLASH_COMMANDS",
    "SessionManager",
    "create_app",
    "render_agents",
    "render_help",
    "render_history",
    "render_result",
    "render_stats",
    "run_cli_ui",
    "run_harness_task",
    "run_tui"]
