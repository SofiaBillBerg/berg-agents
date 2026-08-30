"""Config-driven provider/model registry.

This module is the *single* source of truth for turning a model id into a
concrete :class:`~langchain.chat_models.BaseChatModel`.  There are **no**
hardcoded provider names here: every provider (Ollama, Omniroute, vLLM,
LM Studio, ...) is just an entry in the ``providers`` block of
``config/bergagents.jsonc``::

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

* The provider is derived **from the model id** — never from a global flag.
* A provider's ``options`` map 1:1 onto chat-model constructor kwargs
  (``baseURL`` → ``base_url``, ``apiKey`` → ``api_key``; unknown keys pass
  through verbatim).  Per-model entries may override individual options.
* Missing values become safe defaults (``api_key`` defaults to ``""`` so
  OpenAI-compatible backends that ignore keys keep working).
* ``{env:VAR}`` placeholders in string values are expanded from the
  environment at resolution time.

All call sites (:func:`berg_agents.main.create_llm`, the web server, the
dynamic-model middleware) go through :func:`resolve_model` +
:func:`build_llm`.
"""

from __future__ import annotations

import os
import re
from typing import Any

from langchain.chat_models import BaseChatModel, init_chat_model

__all__ = ["build_llm", "list_models", "load_providers", "resolve_model"]

#: camelCase JSONC option names -> python constructor kwarg names.
_OPTION_KEY_ALIASES: dict[str, str] = {
    "baseURL": "base_url",
    "apiKey": "api_key",
}

#: Matches a whole-string ``{env:VAR}`` / ``${env:VAR}`` placeholder.
_ENV_PATTERN = re.compile(r"^\$?\{env:([A-Za-z_][A-Za-z0-9_]*)}$")

#: Default endpoint when a provider block omits ``baseURL``.
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _expand_value(value: Any) -> Any:
    """Recursively expand ``{env:VAR}`` placeholders in config values.

    A string that is exactly ``{env:VAR}`` expands to the environment
    variable's value, or ``""`` when unset.  Non-string values and dicts /
    lists are handled recursively.

    :param value: Raw config value.
    :return: Value with placeholders expanded.
    """
    if isinstance(value, str):
        match = _ENV_PATTERN.match(value.strip())
        if match:
            return os.environ.get(match.group(1), "")
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
    """Load the ``providers`` block from config.

    When *cfg* is ``None`` the global application settings are used.  If the
    config carries no ``providers`` block (legacy flat-key configs), one is
    synthesized from the deprecated ``ollama_*`` / ``openai_*`` fields so old
    setups keep working until they migrate.

    :param cfg: Optional plain configuration dictionary.
    :return: Mapping of provider name -> provider block (with ``options``
        and ``models`` sub-mappings).
    """
    if cfg is None:
        from berg_agents.config.settings import get_settings

        cfg = get_settings().model_dump()

    raw = cfg.get("providers")
    if isinstance(raw, dict) and raw:
        return raw

    #: --- Legacy synthesis (deprecated flat-key config) ---------------------
    synthesized: dict[str, Any] = {}

    scheme = cfg.get("ollama_scheme", "http")
    host = cfg.get("ollama_host", "localhost")
    port = cfg.get("ollama_port", 11434)
    ollama_model = cfg.get("ollama_model")
    if ollama_model:
        synthesized["ollama"] = {
            "name": "ollama(Local)",
            "options": {"baseURL": f"{scheme}://{host}:{port}/v1"},
            "models": {ollama_model: {}},
        }

    openai_model = cfg.get("openai_model") or cfg.get("model")
    if openai_model:
        synthesized.setdefault(
            "omniroute",
            {
                "name": "OpenAI-compatible",
                "options": {
                    "baseURL": cfg.get("openai_base_url")
                    or cfg.get("base_url")
                    or _DEFAULT_BASE_URL,
                    "apiKey": cfg.get("openai_api_key")
                    or cfg.get("api_key")
                    or "",
                },
                "models": {openai_model: {}},
            },
        )

    return synthesized


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
            kwargs.setdefault("base_url", _DEFAULT_BASE_URL)
            kwargs.setdefault("api_key", "")
            resolved[pname, model_id] = kwargs
    return resolved


def resolve_model(
    model_id: str | None, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve a model id into concrete chat-model constructor kwargs.

    Every OpenAI-compatible backend speaks the same wire protocol, so the
    resolved ``model_provider`` is always ``"openai"`` — the provider block
    only supplies connection options (base_url, api_key, timeouts, ...).

    :param model_id: Model identifier exactly as declared under a provider's
        ``models`` map (e.g. ``"qwen3.5:9b"``).  When ``None`` (or empty),
        the first declared model is used as the default.
    :param cfg: Optional config dict override (defaults to app settings).
    :return: Flat kwargs ready for ``init_chat_model(**kwargs)``.
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
                    **kwargs,
                }
        known = ", ".join(sorted({mid for _, mid in table}))
        raise KeyError(
            f"Model '{model_id}' is not declared in any provider block. "
            f"Known models: {known}. Add it to 'providers' in "
            "config/bergagents.jsonc."
        )

    #: No explicit id -> first declared model is the default.
    for (pname, mid), kwargs in table.items():
        display = kwargs.pop("_display_name", None)
        return {
            "model": mid,
            "model_provider": "openai",
            "_provider": pname,
            "_display_name": display or f"{pname}: {mid}",
            **kwargs,
        }
    raise KeyError(
        "No models configured. Declare a 'providers' block with at least "
        "one model in config/bergagents.jsonc."
    )


def build_llm(resolved: dict[str, Any]) -> BaseChatModel:
    """Construct a concrete ``BaseChatModel`` from :func:`resolve_model` output.

    This is the *pure constructor*: the resolved kwargs are forwarded to
    ``init_chat_model`` verbatim — no configurable_fields proxy, no
    per-provider branching, no key aliasing. An empty ``api_key`` is
    substituted with the conventional ``"EMPTY"`` placeholder because the
    OpenAI client rejects truly empty credentials even on endpoints that
    ignore them.

    :param resolved: Flat kwargs from :func:`resolve_model`.
    :return: A concrete chat-model instance.
    """
    kwargs = {k: v for k, v in resolved.items() if not k.startswith("_")}
    if not kwargs.get("api_key"):
        kwargs["api_key"] = "EMPTY"
    return init_chat_model(**kwargs)


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
            "display_name": display or f"{pname}: {mid}",
        })
    return models
