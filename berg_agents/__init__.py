"""Berg Agents - framework-agnostic multi-agent system.

The main entry point is BergAgentsApp:

    from berg_agents import BergAgentsApp
    app = BergAgentsApp.create()
    app.serve()  # Start web server

Or via CLI:
    python -m berg_agents --web
    python -m berg_agents --tui

**Importing a submodule must not import the application.** This package root is
deliberately lazy: importing ``berg_agents.<anything>`` used to run this file,
which imported ``berg_agents.app`` and the whole harness on the way. That is fine
for a user of the package and wrong for two consumers that import *inside* it:

* the durable workflow runtime re-imports a workflow's module on every replay
  inside a sandbox that forbids nondeterminism — and ``berg_agents.app`` pulls in
  the harness, which calls ``uuid.uuid4()`` (``os.urandom()`` underneath) at
  import time. The runtime refused the run with
  ``SandboxRestrictionError: Cannot call os.urandom() inside a workflow``.
* anything measuring or tracing import cost paid for the app before it asked.

So the public names stay exactly as they were, but resolve on first use through
PEP 562 (``__getattr__``), and importing a submodule runs only this docstring.
``import berg_agents; berg_agents.BergAgentsApp`` behaves as before;
``from berg_agents.workflow.turn import turn`` no longer drags the app in.
"""

from __future__ import annotations

from typing import Any

# Deliberately not a bare re-export list: the exports must resolve on first use
# (see the docstring), which PEP 562 puts in this file rather than in a helper
# module. The rule is waived with the reason kept beside it.
# ruff: ignore[non-empty-init-module]

#: The names this package exports, and the module each lives in. Kept as data
#: so the lazy ``__getattr__`` below stays a lookup rather than a hardcoded
#: ladder, and so a new export is one line here.
_EXPORTS = {
    "AbstractAgent": "berg_agents.core",
    "AgentResult": "berg_agents.core",
    "BergAgentsApp": "berg_agents.app",
    "Harness": "berg_agents.core",
    "RiskLevel": "berg_agents.core",
    "RouterStats": "berg_agents.core",
    "TaskComplexity": "berg_agents.core",
    "TaskContext": "berg_agents.core",
    "get_app": "berg_agents.app"}


def __getattr__(name: str) -> Any:
    """Resolve an export on first use, importing only its own module.

    :param name: The requested public name.
    :return: The attribute from its defining module.
    :raises AttributeError: For a name this package does not export.
    """
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # cache: the second lookup skips this function
    return value


def __dir__() -> list[str]:
    """The package's public names, for ``dir()`` and tab completion."""
    return sorted(set(globals()) | set(_EXPORTS))
