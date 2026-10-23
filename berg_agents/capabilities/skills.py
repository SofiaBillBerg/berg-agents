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

"""On-demand skills for berg_agents chat agents.

Reads ``SKILL.md`` files (YAML frontmatter ``name``/``description`` +
Markdown body - the Anthropic Agent Skills format) from the paths in
``settings.skills`` (``BERG_AGENT_SKILLS``) and wraps each one in a
*deferred* :class:`~pydantic_ai.capabilities.Capability`.

Deferred means cheap: the model only sees a one-line catalog entry
(``id`` + ``description``) and loads the full skill text via the
``load_capability`` tool when the task actually calls for it. Twenty
skills cost ~20 lines of context instead of twenty manuals.

Path rules (each entry is a path or a ``[path, label]`` pair):

- A direct ``SKILL.md`` file → exactly that skill.
- A directory containing ``SKILL.md`` → that skill (``label``, when
  given, overrides the frontmatter name).
- A directory of skill directories (e.g. pointing at ``.agents/skills``)
  → every immediate subdirectory holding a ``SKILL.md``.
- Relative paths resolve against the workspace root, then the repo
  root, then the process working directory - first hit wins.

Unreadable files, missing frontmatter, and empty bodies are skipped
with a warning; skill bodies are capped so one giant manual cannot
flood the context window.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Hard cap per skill body so one manual cannot flood the context.
MAX_SKILL_CHARS = 6000

#: ``---\\nname: x\\ndescription: y\\n---`` frontmatter block.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_skill(path: Path) -> tuple[str, str, str] | None:
    """Parse one ``SKILL.md`` into ``(name, description, body)``.

    Returns ``None`` when the file is unreadable, has no usable
    frontmatter, or carries an empty body.

    :param path: Path to the ``SKILL.md`` file.
    :return: Tuple of (name, description, body) or None on failure.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Skill file unreadable, skipping %s: %s", path, exc)
        return None
    match = _FRONTMATTER_RE.match(text)
    if not match:
        logger.warning("Skill file has no frontmatter, skipping %s", path)
        return None
    name, description = "", ""
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "name" and not name:
            name = value
        elif key == "description" and not description:
            description = value
    body = text[match.end() :].strip()
    if not name or not body:
        logger.warning("Skill file %s missing name or body, skipping", path)
        return None
    if len(body) > MAX_SKILL_CHARS:
        body = body[:MAX_SKILL_CHARS] + "\n\n... (truncated)"
    return name, description, body


def _resolve(entry: str, root_dir: Path, project_root: Path) -> Path | None:
    """Resolve a skill path against root dir, repo root, then CWD.

    :param entry: Raw path string.
    :param root_dir: Workspace root for relative paths.
    :param project_root: Repo root for relative paths.
    :return: Resolved path, or None if not found.
    """
    raw = Path(entry).expanduser()
    if raw.is_absolute() and raw.exists():
        return raw
    for base in (root_dir, project_root, Path.cwd()):
        candidate = (base / raw).resolve()
        if candidate.exists():
            return candidate
    return None


def _collect_candidates(path: Path) -> list[Path]:
    """Expand a resolved path into ``SKILL.md`` files.

    - A direct ``SKILL.md`` file → that skill.
    - A directory containing ``SKILL.md`` → that skill.
    - A directory of skill directories → every immediate subdirectory
      holding a ``SKILL.md``.

    :param path: Resolved path to a file or directory.
    :return: List of ``SKILL.md`` files found (possibly empty).
    """
    if path.is_file():
        return [path] if path.name.lower() == "skill.md" else []
    direct = path / "SKILL.md"
    if direct.is_file():
        return [direct]
    found = []
    try:
        children = sorted(path.iterdir())
    except OSError:
        return []
    for child in children:
        if child.is_dir():
            candidate = child / "SKILL.md"
            if candidate.is_file():
                found.append(candidate)
    return found


def list_skills(
    skill_paths: list[str | list[str]] | None,
    *,
    root_dir: str | Path = ".",
) -> list[dict[str, Any]]:
    """List available skills without building capabilities.

    Name + one-line description + source file per ``SKILL.md`` found,
    using the same path rules as :func:`load_skill_capabilities`.
    Powers the ``GET /api/context`` catalog and the TUI ``/skills``
    listing - no bodies are read beyond frontmatter.

    :param skill_paths: Raw ``settings.skills`` value.
    :param root_dir: Workspace root for relative path resolution.
    :return: List of ``{"name", "description", "source"}`` dicts.
    """
    if not skill_paths:
        return []
    root = Path(root_dir).expanduser().resolve()
    project_root = Path(__file__).resolve().parent.parent.parent
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in skill_paths:
        if isinstance(entry, (list, tuple)):
            raw_path = str(entry[0]) if entry else ""
            label = str(entry[1]) if len(entry) > 1 else ""
        else:
            raw_path, label = str(entry), ""
        resolved = _resolve(raw_path, root, project_root)
        if resolved is None:
            continue
        candidates = _collect_candidates(resolved)
        single = len(candidates) == 1 and (
            resolved.is_file() or (resolved / "SKILL.md").is_file()
        )
        for candidate in candidates:
            parsed = _parse_skill(candidate)
            if parsed is None:
                continue
            name, description, _body = parsed
            skill_id = f"skill-{(label if single else '') or name}"
            if skill_id in seen:
                continue
            seen.add(skill_id)
            found.append({
                "name": skill_id,
                "description": description or f"Skill: {label or name}",
                "source": str(candidate)})
    return found


def load_skill_capabilities(
    skill_paths: list[str | list[str]] | None,
    *,
    root_dir: str | Path = ".",
) -> list[Any]:
    """Build one deferred capability per ``SKILL.md`` found.

    :param skill_paths: Raw ``settings.skills`` value - paths or
        ``[path, label]`` pairs. ``None``/empty means no skills.
    :param root_dir: Workspace root for relative path resolution.
    :return: List of deferred ``Capability`` objects (possibly empty).
    """
    from pydantic_ai.capabilities import Capability

    if not skill_paths:
        return []
    root = Path(root_dir).expanduser().resolve()
    project_root = Path(__file__).resolve().parent.parent.parent
    capabilities: list[Any] = []
    seen: set[str] = set()
    for entry in skill_paths:
        if isinstance(entry, (list, tuple)):
            raw_path = str(entry[0]) if entry else ""
            label = str(entry[1]) if len(entry) > 1 else ""
        else:
            raw_path, label = str(entry), ""
        resolved = _resolve(raw_path, root, project_root)
        if resolved is None:
            logger.warning("Skill path not found, skipping: %s", raw_path)
            continue
        candidates = _collect_candidates(resolved)
        # A label only renames a single skill (direct file or a dir
        # holding exactly one SKILL.md). A directory of skill dirs
        # keeps each skill's own frontmatter name - otherwise every
        # skill would collapse onto one id and dedup would eat them.
        single = len(candidates) == 1 and (
            resolved.is_file() or (resolved / "SKILL.md").is_file()
        )
        for candidate in candidates:
            parsed = _parse_skill(candidate)
            if parsed is None:
                continue
            name, description, body = parsed
            skill_id = f"skill-{(label if single else '') or name}"
            if skill_id in seen:
                continue
            seen.add(skill_id)
            capabilities.append(
                Capability(
                    id=skill_id,
                    description=description or f"Skill: {label or name}",
                    instructions=body,
                    defer_loading=True,
                )
            )
    logger.info(
        "Loaded %d skill(s) as deferred capabilities", len(capabilities)
    )
    return capabilities
