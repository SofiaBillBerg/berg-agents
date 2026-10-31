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

"""Shared SQLite persistence for routing state.

Single source for the router-stats database used by
``core.router_stats.RouterStats`` (insights + adjustments) and the
outcome store (outcomes + router-stats entries).
All tables live in one file: ``{global_config_dir}/router_stats.db`` — the
same global root the session database uses, so agent state is found in one
place whether or not the cwd is a project.

This is a local restart-survival cache for the Router Dashboard — not
learning, and not cross-session memory. Shared Context is the
WHAT/WHY knowledge; MemPalace/Hindsight are optional plugins.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

#: Live tables. ``ensure()`` creates each one and callers of ``insert()``
#: must use a name from this list or the write is silently lost.
TABLES: tuple[str, ...] = (
    "outcomes",  # raw outcome rows (one per execution)
    "router_stats",  # derived per-outcome router-stats entry
    "router_data",  # reserved for aggregate/report payloads
    "router_insights",  # insight dicts (one per recorded outcome)
    "router_adjustments",  # routing-adjustment candidates
)

#: Pre-rename leftovers ("learning" vocabulary). Dropped on ensure so the
#: schema reflects the Router Dashboard naming only.
LEGACY_TABLES: tuple[str, ...] = (
    "learnings",
    "learning_insights",
    "learning_adjustments",
)


def db_path() -> str:
    """Resolve the one router-stats database path.

    Root: the **global** config dir (``~/.berg-agents``), the same root
    the session database lives in — one place for agent state, found
    whether or not the cwd is a project. Set
    ``BERG_AGENT_ROUTER_STATS_DIR`` to relocate it (a deployment with
    its own data volume); the file name stays ``router_stats.db``.

    The old location (``{checkpoint_dir}/agent_state.db``) is no longer
    consulted: two roots for one concern is the duplication ADR-0001
    removes. See ``notes/consolidation-plan-2026-10-28.md``.
    """
    try:
        import os

        from berg_agents.config.paths import global_config_dir

        override = (os.environ.get("BERG_AGENT_ROUTER_STATS_DIR") or "").strip()
        base = Path(override).expanduser() if override else global_config_dir()
        if not base.is_absolute():
            base = (Path.cwd() / base).resolve()
        base.mkdir(parents=True, exist_ok=True)
        return str(base / "router_stats.db")
    except Exception as exc:
        logger.debug("router stats db path fallback: %s", exc)
        return str(Path.cwd() / "router_stats.db")


def ensure(path: str | None = None) -> str:
    """Create the router tables when missing; return the db path.

    Every table name here must match the ``table`` argument a caller
    passes to :func:`insert` — a mismatch is invisible because
    ``insert`` swallows its error, so outcomes were being recorded
    into a table that never existed. Keep this list as the single
    contract; ``insert``/``load`` do not validate.
    """
    db = path or db_path()
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        for table in TABLES:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {table}"
                " (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)"
            )
        # Drop tables left from the pre-rename "learning" vocabulary
        # (no legacy / no back-compat: these are empty-by-design once
        # the rename completed, and their continued presence confuses
        # anyone inspecting the schema).
        for legacy in LEGACY_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {legacy}")
        con.commit()
        con.close()
    except Exception as exc:
        # Visible, not silent: a schema/dir failure here is what made
        # every later insert vanish without a trace (see ADR-0001).
        logger.warning("ensure outcome db failed: %s", exc, exc_info=True)
    return db


def insert(path: str, table: str, payload: dict[str, Any]) -> None:
    """Append one JSON payload row with a UTC timestamp.

    :raises Exception: Callers see the real error. A table name that
        ``ensure()`` did not create used to fail here silently, which
        hid the bug for weeks — the caller decides how to report it.
    """
    import datetime

    con = sqlite3.connect(path)
    try:
        con.execute(
            f"INSERT INTO {table} (ts, data) VALUES (?, ?)",
            (
                datetime.datetime.now(datetime.UTC).isoformat(),
                json.dumps(payload, default=str),
            ),
        )
        con.commit()
    finally:
        con.close()


def load(path: str, table: str, limit: int = 500) -> list[dict[str, Any]]:
    """Load persisted payload rows oldest-first, skipping corrupt rows."""
    rows: list[dict[str, Any]] = []
    try:
        con = sqlite3.connect(path)
        cur = con.cursor()
        for (data,) in cur.execute(
            f"SELECT data FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
        ):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    rows.append(parsed)
            except Exception as exc:
                logger.warning(
                    "outcome db load row failed (%s): %s", table, exc
                )
                continue
        con.close()
    except Exception as exc:
        # A missing table on read is the same schema drift the write
        # path used to hide — report it rather than returning empty.
        logger.warning("outcome db load failed (%s): %s", table, exc)
    rows.reverse()
    return rows
