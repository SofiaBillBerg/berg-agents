"""Pluggable web search/fetch backends.

The web is reached through small backend records, tried in order until
one returns content. Each backend declares the env var gating it
(``None`` = always available) plus ``search``/``fetch`` callables that
return ``str`` on success or ``None`` to pass to the next backend:

- ``ollama`` - Ollama's ``/api/web_search`` + ``/api/web_fetch`` REST
  endpoints (needs ``OLLAMA_API_KEY``).
- ``duckduckgo`` - in-process DuckDuckGo search (no key; needs the
  ``duckduckgo`` extra). Search only.
- ``direct`` - plain HTTPS fetch + markdownify (no key). Fetch only.

Order comes from ``settings.web_search_backends``
(``BERG_AGENT_WEB_SEARCH_BACKENDS``, default
``["ollama", "duckduckgo"]`` for search and the fetch-capable subset
thereof for fetch). Add, remove, or reorder providers in .berg_config -
the chain adapts without code changes. Unknown names are skipped
with a warning.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0
_MAX_CONTENT_CHARS = 8000
_MAX_SNIPPET_CHARS = 600


def _env(name: str) -> str:
    """Read an env var fresh, ensuring the root .env was loaded first.

    :param name: Env var name.
    :return: Env var value (empty string if unset).
    """
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        from berg_agents.config.settings import ensure_env_loaded

        ensure_env_loaded()
    except Exception:
        logger.debug("ensure_env_loaded failed", exc_info=True)
    return os.getenv(name, "").strip()


# -- backend primitives ------------------------------------------------------


def _ollama_search(query: str, max_results: int) -> str | None:
    """Ollama-index search; ``None`` when unusable (no key/failure)."""
    import httpx

    key = _env("OLLAMA_API_KEY")
    if not key:
        return None
    resp = httpx.post(
        "https://ollama.com/api/web_search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "max_results": max_results},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    results = (resp.json() or {}).get("results", [])
    if not results:
        return None
    lines = []
    for i, r in enumerate(results[:max_results], start=1):
        lines.append(
            f"{i}. {r.get('title') or 'untitled'} - {r.get('url', '')}\n"
            f"   {(r.get('content', '') or '').strip()[:_MAX_SNIPPET_CHARS]}"
        )
    return "\n".join(lines)


def _ollama_fetch(url: str) -> str | None:
    """Ollama-index page fetch; ``None`` when unusable.

    :param url: Page URL to fetch.
    :return: Markdownified page content, or None on failure.
    """
    import httpx

    key = _env("OLLAMA_API_KEY")
    if not key:
        return None
    resp = httpx.post(
        "https://ollama.com/api/web_fetch",
        headers={"Authorization": f"Bearer {key}"},
        json={"url": url},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    content = (data.get("content", "") or "").strip()
    if not content:
        return None
    return f"# {data.get('title', url)}\n\n{content[:_MAX_CONTENT_CHARS]}"


def _duckduckgo_search(query: str, max_results: int) -> str | None:
    """In-process DuckDuckGo search; ``None`` on failure.

    :param query: Search query string.
    :param max_results: Max results wanted (clamped to 1-10).
    :return: Formatted search results, or None on failure.
    """
    from ddgs import DDGS

    hits = DDGS().text(query, max_results=max_results) or []
    if not hits:
        return None
    lines = []
    for i, h in enumerate(hits[:max_results], start=1):
        lines.append(
            f"{i}. {h.get('title') or 'untitled'} - {h.get('href', '')}\n"
            f"   {(h.get('body', '') or '').strip()[:_MAX_SNIPPET_CHARS]}"
        )
    return "\n".join(lines)


def _direct_fetch(url: str) -> str | None:
    """Plain HTTPS fetch + markdownify; ``None`` on failure."""
    import httpx
    from markdownify import markdownify

    resp = httpx.get(
        url, timeout=_TIMEOUT_S, headers={"User-Agent": "berg-agents/0.1"}
    )
    resp.raise_for_status()
    text = markdownify(resp.text).strip()
    return text[:_MAX_CONTENT_CHARS] if text else None


@dataclass(frozen=True)
class WebBackend:
    """One named web backend with optional search/fetch support."""

    name: str
    key_var: str | None
    search: Callable[[str, int], str | None] | None = None
    fetch: Callable[[str], str | None] | None = None


#: Registry - data, not branches. Add providers here; select via .berg_config.
BACKENDS: dict[str, WebBackend] = {
    "ollama": WebBackend(
        name="ollama",
        key_var="OLLAMA_API_KEY",
        search=_ollama_search,
        fetch=_ollama_fetch,
    ),
    "duckduckgo": WebBackend(
        name="duckduckgo",
        key_var=None,
        search=_duckduckgo_search,
    ),
    "direct": WebBackend(
        name="direct",
        key_var=None,
        fetch=_direct_fetch,
    )}

DEFAULT_BACKEND_ORDER = ["ollama", "duckduckgo", "direct"]


def _ordered_backends(
        order: list[str] | None, *, kind: str
) -> list[WebBackend]:
    """Resolve configured names to backends supporting *kind*."""
    names = order or DEFAULT_BACKEND_ORDER
    resolved = []
    for name in names:
        backend = BACKENDS.get(str(name).strip().lower())
        if backend is None:
            logger.warning("Unknown web backend %r, skipping", name)
            continue
        if (getattr(backend, kind) or None) is None:
            continue
        resolved.append(backend)
    return resolved


def make_web_search(order: list[str] | None = None) -> Callable[..., str]:
    """Build a ``query``/``max_results`` search function over backends.

    :param order: List of backend names to use, in order.
    :return: A search function.
    """
    backends = _ordered_backends(order, kind="search")

    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web across the configured backends, in order.

        :param query: Search query string.
        :param max_results: Max results wanted (clamped to 1-10).
        :return: Formatted search results, or a message if none found.
        """
        try:
            clamped = max(1, min(int(max_results), 10))
        except (TypeError, ValueError):
            clamped = 5
        attempted: list[str] = []
        for backend in backends:
            attempted.append(backend.name)
            try:
                assert backend.search is not None
                result = backend.search(query, clamped)
            except Exception as exc:
                logger.warning(
                    "Web backend %s search failed: %s", backend.name, exc
                )
                continue
            if result:
                return result
        return (
                f"No web results for {query!r} "
                f"(tried: {', '.join(attempted) or 'no backends'})."
                + (
                    ""
                    if any(
                        (BACKENDS[n].key_var or "")
                        and _env(BACKENDS[n].key_var or "")
                        for n in attempted
                        if n in BACKENDS
                    )
                    else " Set OLLAMA_API_KEY to enable the Ollama index."
                )
        )

    # Distinct __name__ keeps tool schemas readable per configuration.
    web_search.__name__ = "web_search"
    return web_search


def make_web_fetch(order: list[str] | None = None) -> Callable[..., str]:
    """Build a ``url`` fetch function over backends."""
    backends = _ordered_backends(order, kind="fetch")

    def web_fetch(url: str) -> str:
        """Fetch one page across the configured backends, in order.

        :param url: Page URL to fetch.
        :return: Markdownified page content, or a message if none found.
        """
        attempted: list[str] = []
        for backend in backends:
            attempted.append(backend.name)
            try:
                assert backend.fetch is not None
                result = backend.fetch(url)
            except Exception as exc:
                logger.warning(
                    "Web backend %s fetch failed: %s", backend.name, exc
                )
                continue
            if result:
                return result
        return (
            f"Could not fetch {url} "
            f"(tried: {', '.join(attempted) or 'no backends'})."
        )

    web_fetch.__name__ = "web_fetch"
    return web_fetch


def available_backends() -> dict[str, dict[str, Any]]:
    """Backend inventory for diagnostics/UI (no secrets)."""
    inventory: dict[str, dict[str, Any]] = {}
    for name, backend in BACKENDS.items():
        key_var = backend.key_var or ""
        inventory[name] = {
            "search": backend.search is not None,
            "fetch": backend.fetch is not None,
            "key_configured": bool(key_var and _env(key_var)),
            "key_var": key_var or None}
    return inventory


__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND_ORDER",
    "WebBackend",
    "available_backends",
    "make_web_fetch",
    "make_web_search"]
