"""Shared SQLite persistence for learning state.

Single source for the learning database used by
``agents.learning.OutcomeStore`` (outcomes + learning entries) and
``core.learning_gate.LearningGate`` (insights + adjustments).
All tables live in one file: ``{checkpoint_dir}/agent_state.db``.

MemPalace remains the cross-session memory truth (diary + KG);
this SQLite file is the local restart-survival cache, and
``notes/current_goals.md`` is the human-shareable projection.
"""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def db_path() -> str:
    """Resolve the learning SQLite path: ``{checkpoint_dir}/agent_state.db``."""
    try:
        from berg_agents.config.settings import get_settings

        cfg = get_settings()
        raw = cfg.checkpoint_dir or "~/.berg_agents/checkpoints/"
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return str(p / "agent_state.db")
    except Exception as exc:
        logger.debug("outcome db path fallback: %s", exc)
        return str(Path.cwd() / "agent_state.db")


def ensure(path: str | None = None) -> str:
    """Create the learning tables when missing; return the db path."""
    db = path or db_path()
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS outcomes"
            " (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS learnings"
            " (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS learning_insights"
            " (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS learning_adjustments"
            " (id INTEGER PRIMARY KEY, ts TEXT, data TEXT)"
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("ensure outcome db failed: %s", exc)
    return db


def insert(path: str, table: str, payload: dict[str, Any]) -> None:
    """Append one JSON payload row with a UTC timestamp."""
    try:
        import datetime

        con = sqlite3.connect(path)
        con.execute(
            f"INSERT INTO {table} (ts, data) VALUES (?, ?)",
            (
                datetime.datetime.now(datetime.UTC).isoformat(),
                json.dumps(payload, default=str),
            ),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("outcome db insert failed (%s): %s", table, exc)


def load(path: str, table: str, limit: int = 500) -> list[dict[str, Any]]:
    """Load persisted payload rows oldest-first, skipping corrupt rows."""
    rows: list[dict[str, Any]] = []
    try:
        con = sqlite3.connect(path)
        cur = con.cursor()
        for (data,) in cur.execute(
            f"SELECT data FROM {table} ORDER BY id DESC LIMIT ?",
            (limit,),
        ):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    rows.append(parsed)
            except Exception as e:
                logger.debug("outcome db load row failed (%s): %s", table, e)
                continue
        con.close()
    except Exception as exc:
        logger.debug("outcome db load failed (%s): %s", table, exc)
    rows.reverse()
    return rows
