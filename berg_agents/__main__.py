"""Entry point: python -m berg_agents --web / --tui."""

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
