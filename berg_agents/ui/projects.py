# Berg Agents is a sophisticated multi-agent system built with modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
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

"""Project identity — the folder that scopes per-project agent state.

Layout, under the global config dir (so every project is reachable from
any checkout, per ADR-0001):

    ``~/.berg-agents/projects/<project_id>/project.json``
    ``~/.berg-agents/projects/<project_id>/transcripts/<session>.jsonl``
    ``~/.berg-agents/projects/<project_id>/...``  (future concerns)

The project **id** is a readable slug of the project's name, so a human
can browse and filter without opening anything. The authoritative
record (``project.json``) is written once, on first use, and never
rewritten — so a project keeps its id and its ``created_at`` across
renames and restarts.

Two different directories that share a name therefore share an id: the
first one to appear owns the record, and the mismatch is logged rather
than silently reassigned. That is a deliberate trade for readability;
the ``root_dir`` in each transcript's header disambiguates when it
matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Names under the global config dir.
_PROJECTS_DIR = "projects"
_RECORD_NAME = "project.json"

#: Characters kept in a project id.
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 64

_RECORD_VERSION = 1


@dataclass(frozen=True)
class ProjectRef:
    """A resolved project: its id, display name and folder.

    Attributes:
        id: Folder-safe project id (the slug of the name).
        name: Human-readable project name (its directory name).
        root_dir: The project's resolved filesystem root.
        dir: Absolute path of this project's folder.
    """

    id: str
    name: str
    root_dir: str
    dir: Path


def _global_config_dir() -> Path:
    """The global config dir.

    One indirection so tests (and a future multi-root setup) can
    redirect it without editing call sites.
    """
    from berg_agents.config.paths import global_config_dir as _global

    return _global()


def projects_root() -> Path:
    """Root of all projects: ``{global}/projects``."""
    return _global_config_dir() / _PROJECTS_DIR


def project_id_for(name: str | None) -> str:
    """The id a project name maps to.

    :param name: Project display name (its directory name).
    :return: Slug such as ``berg-agents``, or ``unknown-project``.
    """
    raw = (name or "").strip().lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")[:_SLUG_MAX].strip("-")
    return slug or "unknown-project"


def project_dir(project_id: str) -> Path:
    """Folder for one project id (may not exist yet)."""
    return projects_root() / project_id


def _record_path(project_id: str) -> Path:
    return project_dir(project_id) / _RECORD_NAME


def project_name(root_dir: str | Path | None) -> str:
    """Display name of a project root (its directory name).

    :param root_dir: Project root; falls back to the current working
        directory's name when None.
    :return: The directory name, or ``unknown-project`` when unresolvable.
    """
    if root_dir is None:
        return Path.cwd().resolve().name or "unknown-project"
    return Path(root_dir).expanduser().resolve().name or "unknown-project"


def resolve_project(root_dir: str | Path | None) -> ProjectRef:
    """Resolve (creating on first use) the project a root_dir belongs to.

    Writes ``project.json`` on first sight of the id and leaves it alone
    afterwards. A later directory that maps to the same id with a
    different ``root_dir`` keeps the existing record and logs the clash.

    :param root_dir: Project root; None uses the working directory.
    :return: The resolved :class:`ProjectRef`.
    """
    resolved = (
        Path(root_dir).expanduser().resolve()
        if root_dir is not None
        else Path.cwd().resolve()
    )
    name = resolved.name or "unknown-project"
    project_id = project_id_for(name)
    folder = project_dir(project_id)
    record_path = folder / _RECORD_NAME

    if record_path.is_file():
        _warn_on_root_mismatch(record_path, project_id, str(resolved))
    else:
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _RECORD_VERSION,
            "id": project_id,
            "name": name,
            "root_dir": str(resolved),
            "created_at": datetime.now(UTC).isoformat()}
        try:
            record_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            # Without the record the project still resolves; only the
            # stable metadata is lost, so warn loudly and carry on.
            logger.warning(
                "Project record not written for %s: %s", project_id, exc
            )
    return ProjectRef(
        id=project_id, name=name, root_dir=str(resolved), dir=folder
    )


def _warn_on_root_mismatch(
    record_path: Path, project_id: str, root_dir: str
) -> None:
    """Log (do not fix) when a different root maps to an existing id."""
    try:
        recorded = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception:
        return  # Unreadable record: resolve_project already left it.
    existing = str(recorded.get("root_dir") or "")
    if existing and existing != root_dir:
        logger.warning(
            "Project id %r maps to two roots; keeping the first (%s), "
            "this session is %s",
            project_id,
            existing,
            root_dir,
        )


def project_record(project_id: str) -> dict[str, Any] | None:
    """Read one project's record, or None when absent/unreadable."""
    path = _record_path(project_id)
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Project record unreadable (%s): %s", project_id, exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def list_projects() -> list[dict[str, Any]]:
    """Every recorded project, newest record first.

    An id with no readable record is skipped rather than guessed at, and
    ``root_dir`` is reported as the last known value.
    """
    root = projects_root()
    if not root.is_dir():
        return []
    projects: list[dict[str, Any]] = []
    for folder in sorted(root.iterdir(), key=lambda p: p.name):
        if not folder.is_dir():
            continue
        record = project_record(folder.name)
        if record is None:
            logger.debug("Project %r has no record; skipped", folder.name)
            continue
        record.setdefault("id", folder.name)
        projects.append(record)
    projects.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return projects
