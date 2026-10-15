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

"""Entry point: python -m berg_agents --web / --tui."""

from __future__ import annotations

import contextlib
import sys

from berg_agents.app import BergAgentsApp


def main() -> None:
    """Run web (default) or TUI based on args."""
    args = sys.argv[1:]
    if "--tui" in args or "--cli" in args:
        from berg_agents.ui.cli_ui import run_tui

        run_tui()
    else:
        # Default: web server
        host = "0.0.0.0"
        port = 8001
        if "--port" in args:
            with contextlib.suppress(IndexError, ValueError):
                port = int(args[args.index("--port") + 1])
        if "--host" in args:
            with contextlib.suppress(IndexError):
                host = args[args.index("--host") + 1]
        BergAgentsApp.create().serve(host=host, port=port)


if __name__ == "__main__":
    main()
