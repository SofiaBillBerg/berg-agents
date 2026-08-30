"""Library helpers for the *berg_agents* package.

This module exposes the public functions :func:`load_config` and
:func:`create_llm` that the CLI, the agent runtime and the test-suite all
share.  The interactive chat loop lives in :mod:`berg_agents.cli` instead,
so ``python -m berg_agents`` routes there through :mod:`berg_agents.__main__`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from berg_agents.config.jsonc import loads as jsonc_loads
from berg_agents.config.settings import Settings, get_settings
from berg_agents.providers.registry import build_llm, resolve_model
from langchain.chat_models import BaseChatModel
from pydantic_settings import BaseSettings
import yaml

__all__ = ["create_llm", "load_config"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration as a dictionary.

    When *config_path* is provided the JSON or YAML file at that location is
    loaded (override).  When it is ``None`` the typed application
    settings are returned instead, so the ``.env`` file / environment remain
    the single source of truth.

    Supported extensions are ``.json``, ``.yaml`` and ``.yml``; the loader
    is chosen from the file suffix.  A ``FileNotFoundError`` is raised when
    the target does not exist, and a ``ValueError`` for unsupported
    extensions.

    :param config_path: Optional path to a JSON/YAML configuration file.  If
        the path points to a directory, the function will look for ``bergagents.jsonc``,
        ``bergagents.json``, ``bergagents.yml``, ``bergagents.yaml``.
        inside, in that order.

    :returns: Parsed configuration dictionary.
    """  # ruff: noqa: E501
    if config_path is None:
        return get_settings().model_dump()

    cfg_file = Path(config_path)
    if cfg_file.is_dir():
        for candidate in (
            "bergagents.jsonc",
            "bergagents.json",
            "bergagents.yml",
            "bergagents.yaml",
        ):
            probe = cfg_file / candidate
            if probe.exists():
                cfg_file = probe
                break
        else:
            raise FileNotFoundError(
                f"No bergagents.jsonc/.json/yaml/yml found in directory: {config_path}"
            )

    if not cfg_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    suffix = cfg_file.suffix.lower()
    with cfg_file.open("r", encoding="utf-8") as f:
        if suffix == ".jsonc":
            return jsonc_loads(f.read())
        if suffix == ".json":
            return json.load(f)
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(f)
        raise ValueError(
            f"Unsupported config file extension: {suffix!r} "
            f"(expected .jsonc, .json, .yaml or .yml)"
        )


# ---------------------------------------------------------------------------
# LLM construction
# ---------------------------------------------------------------------------


def create_llm(cfg: Settings | dict[str, Any]) -> BaseChatModel:
    """Create an LLM instance from config.

    Resolves the default model through the config-driven provider registry
    (:mod:`berg_agents.providers.registry`) and builds a concrete
    ``BaseChatModel``. The provider is derived from the model id declared in
    the ``providers`` block of ``config/bergagents.jsonc``; legacy flat-key
    configs are synthesized into a registry on the fly.

    :param cfg: Either a :class:`~berg_agents.config.settings.Settings` instance or
        a plain configuration dictionary (e.g. from :func:`load_config`).

    :returns: A :class:`~langchain.chat_models.BaseChatModel`
        instance.
    """
    if isinstance(cfg, BaseSettings):
        cfg = cfg.model_dump()

    resolved = resolve_model(cfg.get("default_model") or None, cfg)
    return build_llm(resolved)
