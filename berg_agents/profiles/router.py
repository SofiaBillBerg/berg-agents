"""Profile routing for BergAgents harness profiles.

This module handles the registration and resolution of agent profiles based on
the model and provider information.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Default location of the user-editable profiles .berg-agents, resolved from the
#: package root so it works regardless of the process working directory.
DEFAULT_PROFILES_CONFIG = (
    Path(__file__).resolve().parent.parent.parent
    / ".berg-agents"
    / "profiles.yaml"
)

#: Stateful registry of profile keys this router has registered, mapping
#: ``provider:model`` key -> source label (``"settings"`` or ``"configuration-file"``).
#: Used by :func:`resolve_profile` to report where a profile came from.
_registered: dict[str, str] = {}


def load_profiles_from_config_file() -> dict[str, Any]:
    """Load the profiles configuration file and return a dict of profile entries.

    Reads :data:`DEFAULT_PROFILES_CONFIG` (YAML; JSON is a YAML subset) and
    returns its top-level mapping.  Returns an empty dict when the file does
    not exist so callers can degrade gracefully.

    :return: Dictionary of profile entries (possibly empty).
    """
    import yaml

    path = DEFAULT_PROFILES_CONFIG
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return dict(data) if isinstance(data, dict) else {}


def excluded_tools_for_model(model_id: str) -> list[str]:
    """Return the merged ``excluded_tools`` patterns for a model id.

    Collects ``excluded_tools`` entries from every harness profile that
    applies to *model_id* - both the bare logical-provider profile (e.g.
    ``"ollama"``) and any exact ``provider:model`` profile - and supports
    glob patterns so entire families can be hidden, e.g. ``"mcp_*"`` to drop
    all MCP tools or ``"mcp_memory__*"``, for one provider only::

        # profiles.yaml
        "ollama":
          excluded_tools:
            - "mcp_*"            # no MCP servers for local models by default
            - generate_test

    :param model_id: Model identifier as declared in the providers block.
    :return: List of exclusion patterns (maybe empty).
    """
    import fnmatch

    from berg_agents.providers.registry import resolve_model

    try:
        provider = resolve_model(model_id).get("_provider", "")
    except KeyError:
        return []

    patterns: list[str] = []
    #: Candidate profile keys: logical provider, exact pairs, wire aliases.
    candidates = [
        provider,
        f"{provider}:{model_id}",
        "openai",
        f"openai:{model_id}"]
    try:
        profiles = load_profiles_from_config_file()
    except Exception:  # ruff: ignore[blind-except] - bad profile file must not kill tool assembly
        profiles = {}
    for key, profile in profiles.items():
        if key in candidates:
            for pat in profile.get("excluded_tools", []) or []:
                if pat not in patterns:
                    patterns.append(pat)
    _ = fnmatch  # used by callers; kept import-local for clarity
    return patterns


def filter_tools_by_exclusions(tools: list[Any], model_id: str) -> list[Any]:
    """Filter a tool list by the model's ``excluded_tools`` patterns.

    Matches exact names and glob patterns (``fnmatch``) against each tool's
    name, e.g. ``mcp_*`` hides every MCP-provided tool.

    :param tools: Tools to filter.
    :param model_id: Model identifier as declared in the providers block.
    :return: The filtered tool list (order preserved).
    """
    import fnmatch

    patterns = excluded_tools_for_model(model_id)
    if not patterns:
        return tools

    def excluded(name: str) -> bool:
        """Return True if *name* matches any of the exclusion patterns.

        :param name: Tool name to check.
        :return: True if the name is excluded, False otherwise.
        """
        return any(fnmatch.fnmatchcase(name, pat) for pat in patterns)

    return [t for t in tools if not excluded(getattr(t, "name", ""))]
