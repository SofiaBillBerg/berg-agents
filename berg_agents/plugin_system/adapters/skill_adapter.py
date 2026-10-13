"""Wrap repo skills (SKILL.md) as plugins.

Migration-guide Phase 1: skills keep working exactly as before — no
file has to move or be rewritten. Each ``SKILL.md`` becomes one
``SkillPluginAdapter`` instance exposing a deferred ``SkillCapability``
(one-line catalog entry; full body loads on demand).

Skill discovery reuses :func:`list_skills` path rules (direct file,
directory with SKILL.md, directory of skill directories), so the
adapter and the chat agent can never disagree about which skills exist.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from berg_agents.plugin_system.discovery.plugin_metadata import PluginMetadata
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.plugin_context import PluginContext
from berg_agents.plugin_system.plugin_contract import SkillCapability

logger = logging.getLogger(__name__)

#: Entry point shared by every skill plugin (the skill file itself
#: travels via per-plugin settings, see register_skill_plugins).
ENTRY_POINT = (
    "berg_agents.plugin_system.adapters.skill_adapter:SkillPluginAdapter"
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Make a plugin-id-safe slug from a skill name.

    :param name: Skill name (e.g. ``"My Skill"`).
    :return: Lowercase dash-joined slug (e.g. ``"my-skill"``).
    """
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "skill"


def skill_plugin_id(name: str) -> str:
    """Plugin id for a skill (``berg-plugin-skill-<slug>``).

    :param name: Skill name.
    :return: Namespaced plugin identifier.
    """
    return f"berg-plugin-skill-{slugify(name)}"


class SkillPluginAdapter(BergPlugin):
    """Wraps one SKILL.md file as a plugin.

    The skill file path arrives via plugin settings (``skill_file``),
    seeded by :func:`register_skill_plugins` — the shared entry point
    cannot carry per-skill arguments.
    """

    def __init__(self) -> None:
        """Initialize the adapter (content loads in on_load)."""
        super().__init__()
        self.skill_file: Path | None = None
        self.skill_name = ""
        self.skill_description = ""
        self.content = ""

    async def on_load(self, context: PluginContext) -> None:
        """Parse the SKILL.md file into name/description/content.

        :param context: Plugin context carrying ``skill_file`` settings.
        """
        self._set_event_bus(context.event_bus, context.plugin_id)
        raw = (context.settings or {}).get("skill_file", "")
        if not raw:
            logger.warning("Skill plugin %s has no skill_file setting", context.plugin_id)
            return
        # NOTE: Reuses the chat skill parser so frontmatter rules stay
        # identical between the adapter and the chat agent.
        from berg_agents.capabilities.skills import _parse_skill

        path = Path(raw).expanduser()
        self.skill_file = path
        parsed = _parse_skill(path)
        if parsed is None:
            logger.warning("Unreadable skill file, skipping %s", path)
            return
        name, description, body = parsed
        self.skill_name = name
        self.skill_description = description
        self.content = body
        logger.info("Skill plugin loaded: %s (%s)", name, path)

    def get_capabilities(self) -> list[SkillCapability]:
        """Return the deferred skill capability (empty when unloaded).

        :return: One ``SkillCapability`` once on_load parsed the file.
        """
        if not self.content:
            return []
        return [
            SkillCapability(
                id=slugify(self.skill_name),
                name=self.skill_name,
                description=self.skill_description,
                content=self.content,
                deferred=True,
            )
        ]


def build_skill_metadata(
    name: str, description: str, skill_file: str
) -> PluginMetadata:
    """Build registry metadata for one skill.

    :param name: Skill name from frontmatter/catalog.
    :param description: One-line skill description.
    :param skill_file: Absolute path to the SKILL.md file.
    :return: Plugin metadata pointing at the shared adapter entry point.
    """
    return PluginMetadata(
        id=skill_plugin_id(name),
        version="0.0.1",
        name=name,
        description=description or f"Skill: {name}",
        source="local",
        path=Path(skill_file).parent,
        entry_point=ENTRY_POINT,
        tags=["skill"],
    )


async def register_skill_plugins(
    manager: Any,
    skill_paths: list[str | list[str]] | None,
    *,
    root_dir: str | Path = ".",
) -> list[str]:
    """Register every skill as an adapter plugin on a manager.

    Uses the manager's existing machinery only: metadata goes into the
    registry, the skill path goes into per-plugin settings (unpersisted),
    and the standard load_all/enable_all lifecycle picks them up.

    :param manager: Initialized ``PluginManager``.
    :param skill_paths: Raw ``settings.skills`` value.
    :param root_dir: Workspace root for relative path resolution.
    :return: Registered plugin ids.
    """
    from berg_agents.capabilities.skills import list_skills
    from berg_agents.plugin_system.exceptions import PluginError

    if not skill_paths:
        return []
    registered: list[str] = []
    for entry in list_skills(skill_paths, root_dir=root_dir):
        metadata = build_skill_metadata(
            entry["name"].removeprefix("skill-"),
            entry["description"],
            entry["source"],
        )
        if manager.registry.get(metadata.id) is not None:
            continue
        try:
            await manager.registry.register(metadata)
        except PluginError as exc:
            logger.warning("Skill plugin registration skipped: %s", exc)
            continue
        # NOTE: Unpersisted per-plugin settings — the skill path is
        # environment-derived (settings), not user configuration.
        await manager.config_manager.update(
            metadata.id, {"skill_file": entry["source"]}, persist=False
        )
        registered.append(metadata.id)
        logger.info("Skill plugin registered: %s", metadata.id)
    return registered
