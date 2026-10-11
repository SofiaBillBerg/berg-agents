"""Shared Pydantic AI ``provider:model`` string resolution.

This module is the single place where a configured model id
becomes the ``provider:model`` string that Pydantic AI
``Agent`` constructors require. Pydantic AI rejects bare
model ids, so every string built here always carries the
``provider:`` prefix taken from the ``providers`` block of
``config/bergagents.jsonc`` (e.g. ``"ollama:qwen3.5:9b"``).

Resolution itself is delegated to
:func:`berg_agents.providers.registry.resolve_model`, which
remains the only source of truth for which provider owns a
model id. This module adds no new lookup logic; it only
formats the already-resolved ``_provider`` + ``model``
pair into the string form, or builds an explicit
:class:`~pydantic_ai.models.openai.OpenAIChatModel` from the
resolved connection options.

By design this module never imports the deleted
``berg_agents.core.model_router``. Every backend speaks the
OpenAI Chat Completions wire format (see
:func:`berg_agents.providers.registry.resolve_model`), so the
explicit model is always an ``OpenAIChatModel`` pointed at
the configured ``base_url`` - never a provider-name string
that would make Pydantic AI guess the backend (and its
environment variables) from the prefix.
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

from typing import Any

from berg_agents.providers.registry import resolve_model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

__all__ = ["resolve_model_instance", "resolve_model_string"]


def resolve_model_string(
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> str:
    """Resolve a model id into a ``provider:model`` string.

    The provider prefix comes from provider config (the
    ``_provider`` key returned by ``resolve_model``), never
    from a global flag, so adding a new OpenAI-compatible
    endpoint needs zero code changes here.

    Args:
        model_id: Model identifier exactly as declared
            under a provider's ``models`` map (for
            example ``"qwen3.5:9b"``). ``None`` (or an
            empty/blank string) selects the first
            declared model as the default.
        cfg: Optional plain configuration dictionary
            override. Defaults to the app settings when
            ``None``.

    Returns:
        The Pydantic AI model string in
        ``provider:model`` format, for example
        ``"ollama:qwen3.5:9b"``. Never a bare id.

    Raises:
        TypeError: If *model_id* is neither ``None``
            nor a string, or *cfg* is neither ``None``
            nor a dictionary.
        KeyError: If *model_id* is not declared in any
            provider block, or no models are
            configured at all.
        ValueError: If the registry resolves to an
            empty provider or model name (defensive;
            should be unreachable).

    Example:
        >>> resolve_model_string(
        ...     "qwen3.5:9b", {"providers": {"ollama": {
        ...         "models": {"qwen3.5:9b": {}}}}}}
        ... )
        'ollama:qwen3.5:9b'
    """
    # Validate at the boundary so callers get a clear
    # TypeError instead of a confusing KeyError below.
    if model_id is not None and not isinstance(model_id, str):
        raise TypeError(
            f"model_id must be a string or None, got {type(model_id).__name__}."
        )
    if cfg is not None and not isinstance(cfg, dict):
        raise TypeError(
            f"cfg must be a dict or None, got {type(cfg).__name__}."
        )

    # A blank string means "no preference", matching the
    # falsy-means-default contract of resolve_model.
    key = model_id if model_id and model_id.strip() else None

    # Single source of truth: provider ownership of the
    # model id lives in the registry, not here.
    resolved = resolve_model(key, cfg)

    # Populated by resolve_model for every known model;
    # .get keeps this defensive if the contract shifts.
    provider = resolved.get("_provider", "")
    model = resolved.get("model", "")

    # Never emit a bare model id: Pydantic AI requires
    # the provider prefix, so fail loudly instead.
    if not provider or not model:
        raise ValueError(
            "Registry resolved to an empty provider "
            "or model name; refusing to build a bare "
            "model string."
        )
    return f"{provider}:{model}"


def resolve_model_instance(
    model_id: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> OpenAIChatModel:
    """Build an explicit OpenAI-compatible model from config.

    Uses the same resolution as :func:`resolve_model_string`
    (provider ownership from the registry, first declared model
    as the default) but returns a ready-to-run model object
    pointed at the configured ``base_url`` with the configured
    ``api_key`` - no provider-name guessing, no process-env
    lookups, no network calls. Construction is fully offline.

    The concrete class follows the provider block's ``"api"``
    option: ``"anthropic-messages"`` builds a native
    :class:`~pydantic_ai.models.anthropic.AnthropicModel`,
    anything else (or nothing) builds an
    :class:`~pydantic_ai.models.openai.OpenAIChatModel`.

    Args:
        model_id: Model identifier exactly as declared
            under a provider's ``models`` map.
            ``None`` (or an empty/blank string) selects
            the first declared model as the default.
        cfg: Optional plain configuration dictionary
            override. Defaults to the app settings when
            ``None``.

    Returns:
        An ``OpenAIChatModel`` bound to the resolved
        endpoint, suitable for ``Agent(...)`` directly.

    Raises:
        TypeError: If *model_id* is neither ``None``
            nor a string, or *cfg* is neither ``None``
            nor a dictionary.
        KeyError: If *model_id* is not declared in any
            provider block, or no models are
            configured at all.
        ValueError: If the registry resolves to an
            empty model name or base URL (defensive;
            should be unreachable).
    """
    # Same boundary validation as the string form so both
    # entry points fail identically on bad input.
    if model_id is not None and not isinstance(model_id, str):
        raise TypeError(
            f"model_id must be a string or None, got {type(model_id).__name__}."
        )
    if cfg is not None and not isinstance(cfg, dict):
        raise TypeError(
            f"cfg must be a dict or None, got {type(cfg).__name__}."
        )

    # A blank string means "no preference", matching the
    # falsy-means-default contract of resolve_model.
    key = model_id if model_id and model_id.strip() else None

    # Single source of truth, shared with the string form.
    resolved = resolve_model(key, cfg)

    # Populated by resolve_model for every known model;
    # .get keeps this defensive if the contract shifts.
    name = resolved.get("model", "")
    base_url = resolved.get("base_url", "")
    # Normalize "" to None: the registry defaults keyless local endpoints
    # (e.g. Ollama) to "", but OpenAIProvider only applies its documented
    # keyless-local workaround ('api-key-not-set') when api_key is None.
    # An explicit "" skips both that workaround and the OPENAI_API_KEY
    # env fallback and is rejected by the openai SDK at construction.
    api_key = resolved.get("api_key", "") or None

    # Never build a model without an endpoint: fail loudly
    # instead of letting the provider SDK guess one.
    if not name or not base_url:
        raise ValueError(
            "Registry resolved to an empty model name "
            "or base URL; refusing to build a model "
            "instance."
        )
    # Provider API flavor (per provider block, e.g.
    # ``"api": "anthropic-messages"``). Default is OpenAI
    # Chat Completions. A Messages-style base URL on the
    # default flavor is a config error, not something to
    # guess at: the OpenAI SDK would append
    # ``/chat/completions`` to it and produce a 404.
    api = str(resolved.get("api", "") or "").strip().lower()
    if api in ("anthropic-messages", "anthropic"):
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        # The Anthropic SDK always appends "/v1/messages" itself, so a
        # base URL already carrying that suffix (the full endpoint path,
        # as users naturally paste it) would double up. Strip it.
        root = base_url.rstrip("/")
        for suffix in ("/v1/messages", "/messages"):
            if root.endswith(suffix):
                root = root[: -len(suffix)] or "/"
                break
        return AnthropicModel(  # type: ignore[return-value]
            name,
            provider=AnthropicProvider(base_url=root, api_key=api_key),
        )
    if base_url.rstrip("/").endswith("/messages"):
        raise ValueError(
            f"Provider base URL {base_url!r} looks like an Anthropic "
            "Messages endpoint, but the provider block does not declare "
            '"api": "anthropic-messages". Add that option instead of '
            "letting the OpenAI client append /chat/completions to it."
        )
    return OpenAIChatModel(
        name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )
