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

"""Configuration directory resolution — one rule for the whole app.

Precedence (first match wins):

1. ``BERG_AGENTS_CONFIG_DIR`` — explicit override, always wins.
2. ``<project_root>/.berg-config`` — the project's current layout.
3. ``<project_root>/.berg-agents`` — the scheme's canonical name.
4. ``~/.berg-agents`` — the global fallback.

Both project names are accepted because the tree historically used
``.berg-agents`` (bergagents.jsonc, mcp.json, plugin configs) while new
per-project state (session DBs) landed in ``.berg-agents``. Accepting
either — rather than renaming live files — keeps existing setup working
and lets the scheme be adopted gradually.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Checkout root of the berg_agents package (this file is
#: berg_agents/config/paths.py → up two).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Directory names, in precedence order, that may hold project config.
_PROJECT_DIR_NAMES = (".berg-config", ".berg-agents")

#: Name used when creating a fresh global directory.
_GLOBAL_DIR_NAME = ".berg-agents"

#: Environment variable that names the plugin checkout directory. Set it when
#: the plugins live anywhere other than ``<project_root>/berg_plugins``.
PLUGINS_DIR_ENV = "BERG_AGENT_PLUGINS_DIR"


def plugins_dir() -> Path:
    """The directory the plugin loader scans for ``berg_plugins/``.

    Never derived from ``__file__``: an installed wheel has no checkout
    around it, so a path relative to this module would resolve inside
    ``site-packages``. The environment variable wins; otherwise the
    conventional checkout location next to the project root.

    :return: Absolute path to the plugins directory (may not exist).
    """
    override = os.environ.get(PLUGINS_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "berg_plugins"


def project_root() -> Path:
    """The checkout root (parent of the ``berg_agents`` package)."""
    return _PROJECT_ROOT


def global_config_dir() -> Path:
    """The global shared config dir (``~/.berg-agents``).

    The project overlay (:func:`resolve_config_dir`) shadows this per
    section; the Shared Context layer reads both, so this is the one
    place the global location is defined.

    :return: Absolute path to the global config dir.
    """
    return Path.home() / _GLOBAL_DIR_NAME


def resolve_config_dir(root: Path | None = None) -> Path:
    """Resolve the config directory this process should read and write.

    :param root: Project root; defaults to this checkout.
    :return: The directory to use. Created by the caller when needed.
    """
    # 1) Explicit override always wins.
    override = (os.environ.get("BERG_AGENTS_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()

    base = Path(root) if root is not None else _PROJECT_ROOT

    # 2-3) Existing project layout, in precedence order.
    for name in _PROJECT_DIR_NAMES:
        candidate = base / name
        if candidate.is_dir():
            return candidate

    # 4) Global fallback.
    return Path.home() / _GLOBAL_DIR_NAME


def config_file(filename: str, root: Path | None = None) -> Path:
    """Path of a named file inside the resolved config directory.

    :param filename: File name (e.g. ``"bergagents.jsonc"``).
    :param root: Project root; defaults to this checkout.
    :return: Resolved absolute path.
    """
    return resolve_config_dir(root) / filename


def plugin_config_dir(plugin_id: str, root: Path | None = None) -> Path:
    """Config directory dedicated to one plugin.

    Plugins own their config under ``<config-dir>/.<slug>/`` (e.g.
    ``.berg-agents/.shared_todo/config.yaml``), keyed by the slug
    derived from the plugin id.

    :param plugin_id: Plugin identifier.
        :param root: Project root; defaults to this checkout.
    :return: The plugin's directory (may not exist yet).
    """
    from plugin_system import plugin_slug

    return resolve_config_dir(root) / f".{plugin_slug(plugin_id)}"
