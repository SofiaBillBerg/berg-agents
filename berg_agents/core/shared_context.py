# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Shared Context foundation: human-owned, evolving, with history, scoped.

This is the persistent foundation that individual sessions (and agents)
leverage; a session is not the shared context, it is a transient instance
that reads from and contributes to this. Self-hosted under the config
dir, plain files so the human owns and edits it in any editor.

Two orthogonal structures, kept deliberately separate:

**Layer (scope).** A global layer (``~/.berg-agents/context``, shared
across projects) with a project layer (``<project>/.../context``) on top.
One rule, no hidden merging: per section the project content shadows the
global when present, otherwise the global shows. Writes default to the
project layer; pass ``scope="global"`` to author shared context.

**Within a layer.** The current state is plain Markdown at
``<root>/<section>.md`` (what the human edits and the agent renders), and
the history is an append-only JSONL journal at
``<root>/.history/<section>.jsonl`` where every change records
who/what/when/**why**. The why is the point: learning here is what-and-why,
never bare outcome counters.

See ``notes/session-model-map.md`` and the session-model baseline note
under ``notes/`` (the Human/Berg Collaborative Session doc).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

#: Canonical human-authored sections, in render order. One plain file each
#: so the human edits them independently; the names are the vocabulary.
SECTIONS: tuple[str, ...] = (
    "preferences",  # likes/dislikes; how work should be done
    "knowledge",  # durable facts about project/framework (avoid re-research)
    "research",  # findings worth keeping
    "work-notes",  # ongoing work notes
    "project",  # what the project is and how it works well
    "task-state",  # current task, status, open threads
    "files",  # relevant files and references
    "notes",  # freeform things worth remembering
    "learnings",  # what/why insights - never bare counters
)


@dataclass
class _Layer:
    """One rooted context store: current files plus a per-section journal."""

    #: Directory holding ``<section>.md`` files and the ``.history`` dir.
    root: Path
    #: ``"global"`` or ``"project"`` - provenance recorded in the journal.
    scope: str

    def path_for(self, section: str) -> Path:
        """Current-state file for one section."""
        return self.root / f"{section}.md"

    def _journal_for(self, section: str) -> Path:
        """Append-only history file for one section."""
        return self.root / ".history" / f"{section}.jsonl"

    def ensure(self) -> None:
        """Create the store and its journal dir if missing."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".history").mkdir(parents=True, exist_ok=True)

    def read(self, section: str) -> str:
        """Read one section, empty when it has never been written."""
        path = self.path_for(section)
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def write(
        self, section: str, body: str, *, author: str = "human", why: str = ""
    ) -> bool:
        """Overwrite one section and journal the change.

        :param section: Section name.
        :param body: Full new content for the file.
        :param author: Who made the change (``"human"`` or an agent id).
        :param why: Reason for the change; the what/why discipline wants
            it filled for substantive edits.
        :return: True when the content actually changed (and was journaled).
        """
        self.ensure()
        previous = self.read(section)
        if previous == body:
            return False
        self.path_for(section).write_text(body, encoding="utf-8")
        self._journal(
            section,
            author=author,
            why=why,
            summary=self._summarize(previous, body),
        )
        return True

    def append(
        self, section: str, text: str, *, author: str = "human", why: str = ""
    ) -> bool:
        """Append a line/block to one section, preserving a trailing newline.

        :param section: Section name.
        :param text: Text to add on a new line.
        :param author: Who made the change.
        :param why: Reason for the change.
        :return: True when the content changed.
        """
        existing = self.read(section)
        separator = "" if (not existing or existing.endswith("\n")) else "\n"
        return self.write(
            section, f"{existing}{separator}{text}", author=author, why=why
        )

    def history(self) -> list[dict[str, Any]]:
        """Read this layer's journal entries across all sections."""
        records: list[dict[str, Any]] = []
        for section in SECTIONS:
            path = self._journal_for(section)
            if not path.is_file():
                continue
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # A torn/partial line never breaks the whole read.
                    continue
        return records

    def _journal(
        self, section: str, *, author: str, why: str, summary: str
    ) -> None:
        """Append one record to a section's history journal."""
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "scope": self.scope,
            "section": section,
            "change": "write",
            "author": author,
            "why": why,
            "summary": summary}
        self._journal_for(section).parent.mkdir(parents=True, exist_ok=True)
        with self._journal_for(section).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _summarize(previous: str, current: str) -> str:
        """One-line description of a write's delta for the journal."""
        if not previous:
            return "created"
        if not current:
            return "cleared"
        before = len(previous.splitlines())
        after = len(current.splitlines())
        return f"updated ({before} -> {after} lines)"


@dataclass
class SharedContext:
    """Scoped overlay of context stores, global first then project.

    Reads apply one rule: a section's project content shadows the global
    when present, otherwise the global shows. Writes target the project
    layer by default; ``scope="global"`` authors the shared layer.
    """

    #: Layers ordered global -> project; the last is the write default.
    layers: tuple[_Layer, ...]

    @classmethod
    def resolve(cls, root_dir: Path | None = None) -> SharedContext:
        """Resolve (and create) the global and project context stores.

        :param root_dir: Explicit project root; defaults to this checkout
            via the same single-source rule as the rest of the app.
        :return: A scoped overlay (deduplicated when both scopes resolve
            to the same directory, e.g. the global fallback).
        """
        from berg_agents.config.paths import (
            global_config_dir,
            resolve_config_dir,
        )

        project_dir = resolve_config_dir(root_dir) / "context"
        global_dir = global_config_dir() / "context"
        layers: list[_Layer] = []
        seen: set[str] = set()
        for scope, root in (("global", global_dir), ("project", project_dir)):
            if str(root) in seen:
                continue
            seen.add(str(root))
            layer = _Layer(root=root, scope=scope)
            layer.ensure()
            layers.append(layer)
        return cls(layers=tuple(layers))

    def project(self) -> _Layer:
        """The project layer (write default, shadows global on reads)."""
        return self.layers[-1]

    def global_(self) -> _Layer:
        """The global (shared) layer."""
        return self.layers[0]

    def _layer_for(self, scope: str) -> _Layer:
        """The layer a write targets."""
        return self.project() if scope == "project" else self.global_()

    def read(self, section: str) -> str:
        """Effective content for a section (project shadows global)."""
        result = ""
        for layer in self.layers:
            body = layer.read(section)
            if body.strip():
                result = body
        return result

    def write(
        self,
        section: str,
        body: str,
        *,
        author: str = "human",
        why: str = "",
        scope: str = "project",
    ) -> bool:
        """Overwrite one section in a given scope and journal it."""
        return self._layer_for(scope).write(
            section, body, author=author, why=why
        )

    def append(
        self,
        section: str,
        text: str,
        *,
        author: str = "human",
        why: str = "",
        scope: str = "project",
    ) -> bool:
        """Append to one section in a given scope and journal it."""
        return self._layer_for(scope).append(
            section, text, author=author, why=why
        )

    def render(self, sections: tuple[str, ...] = SECTIONS) -> str:
        """Join non-empty sections into one prompt-injectable block."""
        chunks: list[str] = []
        for section in sections:
            body = self.read(section).strip()
            if body:
                chunks.append(f"## {section}\n{body}")
        return "\n\n".join(chunks)

    def history(self, section: str | None = None) -> list[dict[str, Any]]:
        """Journal entries across layers, newest first.

        :param section: Restrict to one section; ``None`` reads all.
        :return: Merged, timestamp-sorted (descending) journal records.
        """
        records: list[dict[str, Any]] = []
        for layer in self.layers:
            records.extend(layer.history())
        if section:
            records = [r for r in records if r.get("section") == section]
        records.sort(key=lambda r: str(r.get("ts", "")), reverse=True)
        return records

    def scopes(self) -> dict[str, str]:
        """Where each scope lives (for the UI / debugging)."""
        return {layer.scope: str(layer.root) for layer in self.layers}
