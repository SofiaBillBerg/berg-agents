"""Tools for the berg_agents package."""

# Public re-export so consumers (and tests) import from the package
# root instead of the private ``_io`` module (ruff PLC2701).
from berg_agents.tools._io import create_from_template

__all__ = ["create_from_template"]
