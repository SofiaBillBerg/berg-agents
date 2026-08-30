"""Dynamic model selection middleware for deepagents.

Implements the LangChain-recommended pattern for selecting a model at runtime:
a ``wrap_model_call`` middleware reads the model id from invocation context,
resolves it through the config-driven provider registry
(:mod:`berg_agents.providers.registry`), and builds a concrete model
on-the-fly. There are no hardcoded provider names here — the provider,
base_url and api_key all follow from the model's entry in the ``providers``
block of ``config/bergagents.jsonc``.

This avoids rebuilding the agent on every model switch — the agent is built
once with a default model, and the middleware transparently swaps the model
per-invocation based on the context passed by the caller (web UI or TUI).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from berg_agents.providers.registry import build_llm, resolve_model
from langchain.agents.middleware import (
    ModelRequest,
    ModelResponse,
    wrap_model_call,
)

@dataclass
class ModelContext:
    """Runtime context carrying the user's model selection.

    Passed as ``context=ModelContext(...)`` to ``agent.invoke()`` / ``ainvoke()``.
    The ``configurable_model`` middleware reads this to select the active model.

    :param model: Model identifier exactly as declared under a provider's
        ``models`` map in ``config/bergagents.jsonc`` (e.g. ``"qwen3.5:9b"``).
    :param base_url: Optional override for the resolved base URL.
    """

    model: str = ""
    base_url: str | None = None


@wrap_model_call
def configurable_model(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Middleware that swaps the model at invocation time based on context.

    Reads ``ModelContext`` from ``request.runtime.context``, resolves the
    model id via the registry, builds a concrete model, and forwards the
    request with the overridden model.

    :param request: The incoming model request (carries runtime context).
    :param handler: The next handler in the middleware chain.
    :return: The model response from the handler.
    """
    ctx = getattr(request.runtime, "context", None)
    if ctx is None or not isinstance(ctx, ModelContext) or not ctx.model:
        # No model context → use the agent's default model as-is.
        return handler(request)

    # Resolve connection options from the model's provider block; apply any
    # explicit per-request base_url override on top.
    resolved = resolve_model(ctx.model)
    if ctx.base_url:
        resolved["base_url"] = ctx.base_url

    # build_llm always returns a real BaseChatModel — never the lazy proxy.
    new_model = build_llm(resolved)

    return handler(request.override(model=new_model))
