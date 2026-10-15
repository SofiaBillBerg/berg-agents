# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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
    models = (
        ((cfg.get("model_routing") or {}).get("models") or {}).get(level) or {}
    ).get("models") or []
    return str(models[0]) if models else None
