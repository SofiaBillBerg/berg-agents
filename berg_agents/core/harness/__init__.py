"""Harness package — re-exports for backward compatibility.

New code should import from `berg_agents.core.harness.orchestrator`.
`berg_agents.core.harness` (the old flat module) is now a package.
"""

from berg_agents.core.harness.orchestrator import Harness

__all__ = ["Harness"]
