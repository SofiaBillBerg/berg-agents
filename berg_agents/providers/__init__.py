"""Provider layer - model resolution.

The only public surface is :func:`resolve_model_instance`, which reads
``.berg-agents/bergagents.jsonc`` and returns a fully-configured
:class:`~pydantic_ai.models.openai.OpenAIChatModel`. The old ``LLMProvider``
protocol / ``ProviderBase`` ABC were removed as dead code (nobody subclasses
or instantiates them).
"""

from __future__ import annotations

from .models import resolve_model_instance, resolve_model_string

__all__ = ["resolve_model_instance", "resolve_model_string"]
