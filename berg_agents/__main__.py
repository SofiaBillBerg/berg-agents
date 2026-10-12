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
