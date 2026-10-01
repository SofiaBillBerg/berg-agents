"""Complexity routing - single source for complexity → model.

Single axis: task complexity levels (trivial/standard/complex/critical)
map directly onto models. There are no separate "small/medium/large"
tiers - that parallel vocabulary is deleted. Every caller
(`agents/implementation`, `agents/planner`, `core/harness`,
`profiles/router`) imports from here.
"""

from __future__ import annotations

from typing import Any

from berg_agents.config.settings import get_settings


COMPLEXITY_LEVELS = ["trivial", "standard", "complex", "critical"]
DEFAULT_COMPLEXITY = "standard"


def model_for_complexity(
    complexity: str, cfg: dict[str, Any] | None = None
) -> str | None:
    """Return the first model id declared for a complexity level.

    Reads ``model_routing.models`` from config; each level carries
    its own ``models`` list plus ``max_tokens``.

    Args:
        complexity: Complexity level (e.g. ``"standard"``).
        cfg: Optional plain configuration dictionary.

    Returns:
        First model id of the level, or None when unknown/empty.
    """
    if cfg is None:
        cfg = get_settings().model_dump()
    level = (complexity or DEFAULT_COMPLEXITY).strip().lower()
    if level not in COMPLEXITY_LEVELS:
        level = DEFAULT_COMPLEXITY
    models = (
        ((cfg.get("model_routing") or {}).get("models") or {}).get(level) or {}
    ).get("models") or []
    return str(models[0]) if models else None
