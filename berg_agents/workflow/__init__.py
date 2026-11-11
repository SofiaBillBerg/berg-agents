"""berg's own durable workflow runtime.

Importing this package registers berg's workflows on the registry: a workflow is
only known to the runtime's consumer once its module has been imported in the
same process, which is why ``turn`` is imported here rather than left to whoever
needs it (the SDK's own error for the missing case is
``KeyError: 'workflow//<module>//<name>'``).

The order matters: the registry first, then the modules that declare workflows
on it.
"""

from __future__ import annotations

# Registers berg's workflows and steps on `wf`. Imported for the side effect,
# so the linter is told why the name is unused.
from berg_agents.workflow import turn as _turn  # ruff: ignore[unused-import]
from berg_agents.workflow.registry import Chunk, start_worker, wf

__all__ = ["Chunk", "start_worker", "wf"]
