# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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
    models = _level_models(cfg, level)
    return str(models[0]) if models else None


def _level_models(cfg: dict[str, Any], level: str) -> list[str]:
    """The models one complexity level declares, in order.

    Args:
        cfg: Plain configuration dictionary.
        level: Complexity level name.

    Returns:
        The level's model ids in declaration order, best first.
    """
    return [
        str(model)
        for model in (
            ((cfg.get("model_routing") or {}).get("models") or {}).get(level)
            or {}
        ).get("models")
        or []
    ]


def failover_chain(
    model_id: str | None, cfg: dict[str, Any] | None = None
) -> list[str]:
    """The models to try for a run, in order, starting from its own.

    A tier's declared order is the failover order: the first entry is the
    preference and the rest are the fallbacks, which is the only ordering
    berg already maintains. A model that appears in no tier — a one-off the
    caller named explicitly — has no fallback, so its chain is itself alone.

    Args:
        model_id: The model the run would use first.
        cfg: Optional plain configuration dictionary.

    Returns:
        Models to try in order, first being ``model_id`` when it is set.
    """
    if cfg is None:
        cfg = get_settings().model_dump()
    if not model_id:
        return []
    for level in COMPLEXITY_LEVELS:
        models = _level_models(cfg, level)
        if model_id in models:
            return models[models.index(model_id) :]
    return [model_id]
