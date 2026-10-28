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

"""Config-driven provider/model registry.

This module is the *single* source of truth for turning a model id into
a dictionary of chat-model constructor kwargs.  There are **no**
hardcoded provider names here: every provider (Ollama, Omniroute, vLLM,
LM Studio, ...) is just an entry in the ``providers`` block of
``.berg-agents/bergagents.jsonc``::

    "providers": {
      "ollama": {
        "name": "ollama(Local)",
        "options": {
          "baseURL": "{env:OLLAMA_BASE_URL}"
        },
        "models": {
          "qwen3.5:9b": {},
          "mistral:latest": {}
        }
      },
      "omniroute": {
        "options": {
          "baseURL": "http://localhost:20128/v1",
          "apiKey": "{env:OMNIROUTE_API_KEY}"
        },
        "models": {"auto": {}, "best-free": {}}
      }
    }

Resolution rules (the "pure constructor" pattern):

* The provider is derived **from the model id** - never from a global flag.
* A provider's ``options`` map 1:1 onto chat-model constructor kwargs
  (``baseURL`` → ``base_url``, ``apiKey`` → ``api_key``; unknown keys pass
  through verbatim).  Per-model entries may override individual options.
* Missing values become safe defaults (``api_key`` defaults to ``""`` so
  OpenAI-compatible backends that ignore keys keep working).
* ``{env:VAR}`` placeholders in string values are expanded from the
  environment at resolution time.

All call sites (:func:`berg_agents.main.`, the web server, the
dynamic-model middleware) go through :func:`resolve_model`.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

__all__ = [
    "first_declared_model",
    "list_models",
    "load_providers",
    "resolve_model"]

#: camelCase JSONC option names -> python constructor kwarg names.
_OPTION_KEY_ALIASES: dict[str, str] = {
    "baseURL": "base_url",
    "apiKey": "api_key"}

#: Matches a whole-string ``{env:VAR}`` / ``${env:VAR}`` placeholder.
_ENV_PATTERN = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)}$")

#: Default endpoint when a provider block omits ``baseURL``.
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _expand_value(value: Any) -> Any:
    """Recursively expand ``${env:VAR}`` / ``${VAR}`` placeholders in configuration file values.

    A string that is exactly ``${env:VAR}`` or ``${VAR}`` expands to the environment
    variable's value, or ``""`` when unset.  Non-string values and dicts /
    lists are handled recursively. Falls back to `.env` file when the var
    is not yet in the process env (import-time before dotenv loads).

    :param value: Raw config value.
    :return: Value with placeholders expanded.
    """
    if isinstance(value, str):
        match = _ENV_PATTERN.match(value.strip())
        if match:
            var = match.group(1)
            if var in os.environ:
                return os.environ[var]
            # Fallback to .env file before dotenv has loaded (import-time)
            try:
                from pathlib import Path

                from dotenv import dotenv_values

                # registry.py is at berg_agents/providers/registry.py -> root is 3 parents up
                root = Path(__file__).resolve().parent.parent.parent
                vals = dotenv_values(root / ".env") or {}
                if vals.get(var) is not None:
                    return vals[var]
            except Exception as e:
                lgogger = logging.getLogger(__name__)
                lgogger.warning(
                    "Failed to read .env file for variable expansion: %s", e
                )
            return ""
        return value
    if isinstance(value, dict):
        return {k: _expand_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_value(v) for v in value]
    return value


def _normalize_options(options: dict[str, Any]) -> dict[str, Any]:
    """Map camelCase option keys onto constructor kwargs, pass the rest through.

    :param options: Provider/model option mapping (already env-expanded).
    :return: Normalized keyword arguments for the chat-model constructor.
    """
    normalized: dict[str, Any] = {}
    for key, val in options.items():
        normalized[_OPTION_KEY_ALIASES.get(key, key)] = val
    return normalized


def load_providers(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load the ``providers`` block from .berg-agents configuration file.

    When *cfg* is ``None`` the global application settings are used.  Every
    active setup declares a ``providers`` block directly; this function
    returns it unchanged.

    :param cfg: Optional plain configuration dictionary.
    :return: Mapping of provider name -> provider block (with ``options``
        and ``models`` sub-mappings).
    """
    if cfg is None:
        from berg_agents.config.settings import get_settings

        cfg = get_settings().model_dump()

    raw = cfg.get("providers") if cfg else None
    if isinstance(raw, dict) and raw:
        return raw

    return {}


def fallback_model_id(cfg: dict[str, Any] | None = None) -> str | None:
    """The config-named default model, when a provider declares it.

    Used when a configured tier default cannot be resolved. Deliberately
    NOT "the first model in the providers block": that is file order, so
    it handed back whichever provider happens to be listed first — which
    on this checkout is the 30B unsloth model, silently making a typo
    resource-expensive. ``defaultModel`` is a deliberate, config-owned
    choice, so it is the honest fallback.

    :param cfg: Optional plain configuration dictionary.
    :return: ``defaultModel`` when declared by some provider, else None.
    """
    if cfg is None:
        from berg_agents.config.settings import get_settings

        cfg = get_settings().model_dump()
    default = cfg.get("defaultModel")
    if not isinstance(default, str) or not default.strip():
        return None
    wanted = default.strip()
    for block in load_providers(cfg).values():
        models = block.get("models") if isinstance(block, dict) else None
        if not isinstance(models, dict):
            continue
        for model_id in models:
            if model_id == wanted or model_id.endswith(f"/{wanted}"):
                return model_id
    return None


def _declared_default(cfg: dict[str, Any] | None = None) -> str | None:
    """The configured ``defaultModel`` when a provider declares it.

    Kept private: :func:`resolve_model` consults it in its "no explicit
    id" branch so that branch honours the config choice rather than
    declaration order.

    :param cfg: Optional plain configuration dictionary.
    :return: ``defaultModel`` when declared, else None.
    """
    if cfg is None:
        from berg_agents.config.settings import get_settings

        cfg = get_settings().model_dump()
    default = cfg.get("defaultModel")
    if not isinstance(default, str) or not default.strip():
        return None
    wanted = default.strip()
    for block in load_providers(cfg).values():
        models = block.get("models") if isinstance(block, dict) else None
        if isinstance(models, dict) and wanted in models:
            return wanted
    return None


def first_declared_model(cfg: dict[str, Any] | None = None) -> str | None:
    """The first model id any provider declares, or None when none do.

    Last resort only: providers are iterated in config-file order, so a
    setup that lists a large model first gets the large model. Prefer
    :func:`fallback_model_id`.

    :param cfg: Optional plain configuration dictionary.
    :return: Model id such as ``"ollama/gemma:12b"`` (the provider
        prefix :func:`resolve_model` expects), or None.
    """
    for block in load_providers(cfg).values():
        models = block.get("models") if isinstance(block, dict) else None
        if isinstance(models, dict) and models:
            return str(next(iter(models)))
    return None


def _iter_model_kwargs(
    providers: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Build ``(provider_name, model_id) -> resolved kwargs`` for every model.

    Merges provider-level ``options`` with per-model overrides and applies
    the safe defaults (``api_key=""``, ``baseURL`` fallback).

    :param providers: Raw providers block.
    :return: Mapping of ``(provider, model_id)`` to constructor kwargs
        (without ``model`` / ``model_provider`` themselves).
    """
    resolved: dict[tuple[str, str], dict[str, Any]] = {}
    for pname, block in providers.items():
        if not isinstance(block, dict):
            continue
        provider_options = _normalize_options(
            _expand_value(block.get("options", {}))
        )
        models = block.get("models", {})
        if not isinstance(models, dict):
            continue
        for model_id, entry in models.items():
            kwargs = dict(provider_options)
            if isinstance(entry, dict):
                kwargs.update(
                    _normalize_options(_expand_value(entry.get("options", {})))
                )
                #: Allow an explicit per-model display/base override key.
                if entry.get("name"):
                    kwargs["_display_name"] = entry["name"]
            # Empty string from missing ${env:VAR}/${VAR} should fallback to default (happens before dotenv loads at import time)
            if not kwargs.get("base_url"):
                kwargs["base_url"] = _DEFAULT_BASE_URL
            kwargs.setdefault("api_key", "")
            resolved[pname, model_id] = kwargs
    return resolved


def resolve_model(
    model_id: str | None, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve a model id into concrete chat-model constructor kwargs.

    Every OpenAI-compatible backend speaks the same wire protocol, so the
    resolved ``model_provider`` is always ``"openai"`` - the provider block
    only supplies connection options (base_url, api_key, timeouts, ...).

    :param model_id: Model identifier exactly as declared under a provider's
        ``models`` map (e.g. ``"qwen3.5:9b"``).  When ``None`` (or empty),
        the first declared model is used as the default.
    :param cfg: Optional config dict override (defaults to app settings).
    :return: Flat kwargs ready for a chat-model constructor.
    :raises KeyError: If *model_id* is not declared in any provider block.
    """
    providers = load_providers(cfg)
    table = _iter_model_kwargs(providers)

    if model_id:
        for (pname, mid), kwargs in table.items():
            if mid == model_id:
                display = kwargs.pop("_display_name", None)
                return {
                    "model": mid,
                    "model_provider": "openai",
                    "_provider": pname,
                    "_display_name": display or f"{pname}: {mid}",
                    **kwargs}
        known = ", ".join(sorted({mid for _, mid in table}))
        raise KeyError(
            f"Model '{model_id}' is not declared in any provider block. "
            f"Known models: {known}. Add it to 'providers' in "
            ".berg-agents/bergagents.jsonc."
        )

    #: No explicit id -> the configured ``defaultModel`` is the default.
    # That is a deliberate config choice, whereas "first declared" is
    # merely file order: a setup listing a large provider first would
    # silently hand back that large model (observed: the 30B unsloth
    # model for a ``None`` guardian/planner lookup). Fall back to the
    # first declared id only when ``defaultModel`` is unset or the
    # provider block it names is gone.
    for (pname, mid), kwargs in table.items():
        if mid == _declared_default(cfg):
            display = kwargs.pop("_display_name", None)
            return {
                "model": mid,
                "model_provider": "openai",
                "_provider": pname,
                "_display_name": display or f"{pname}: {mid}",
                **kwargs}
    #: ``defaultModel`` unset or no longer declared: first declared id.
    for (pname, mid), kwargs in table.items():
        display = kwargs.pop("_display_name", None)
        return {
            "model": mid,
            "model_provider": "openai",
            "_provider": pname,
            "_display_name": display or f"{pname}: {mid}",
            **kwargs}
    raise KeyError(
        "No models configured. Declare a 'providers' block with at least "
        "one model in .berg-agents/bergagents.jsonc."
    )


def list_models(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """List every declared model for UI selectors.

    :param cfg: Optional config dict override.
    :return: List of ``{"provider", "model", "base_url", "display_name"}``
            dicts in declaration order.
    """
    providers = load_providers(cfg)
    models: list[dict[str, Any]] = []
    for (pname, mid), kwargs in _iter_model_kwargs(providers).items():
        display = kwargs.pop("_display_name", None)
        models.append({
            "provider": pname,
            "model": mid,
            "base_url": kwargs.get("base_url"),
            "display_name": display or f"{pname}: {mid}"})
    return models
