"""Framework adapters for berg_agents.

Backends provide pluggable LLM framework support:
- LangChain/LangGraph (langchain_adapter)
- Native/raw LLM calls (native_adapter, future)
"""

from berg_agents.backends.langchain_adapter import (
    LangChainAdapter,
    LangGraphAgent,
    is_langchain_available,
)
from berg_agents.backends.native_adapter import NativeAdapter, NativeAgent

__all__ = [
    "LangChainAdapter",
    "LangGraphAgent",
    "NativeAdapter",
    "NativeAgent",
    "is_langchain_available",
]
