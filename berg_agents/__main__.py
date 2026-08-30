"""Main entry point for the berg_agents package.

This module provides the command-line interface for the berg_agents package.
When run as `python -m berg_agents`, it starts the Typer CLI defined in
:mod:`berg_agents.cli`.
"""

from berg_agents.cli import main

if __name__ == "__main__":
    main()
