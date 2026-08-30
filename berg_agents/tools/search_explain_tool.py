"""Search and explain tool for the berg_agents package."""

from __future__ import annotations

import json
from pathlib import Path
import re

from ._io import FileObject

from langchain.chat_models import BaseChatModel
from langchain.messages import HumanMessage
from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

_MAX_FILE_SIZE: int = 2 * 1024 * 1024  # 2MB


class SearchExplainArgs(BaseModel):
    """Arguments schema for searching and explaining code.

    The search query can be a string or a regular expression.

    Attributes:
        search_query: Term or regexp to search.
        max_results: Maximum number of hits to return.
    """

    search_query: str = Field(..., description="Term or regexp to search")
    max_results: int = Field(10, description="Maximum number of hits to return")


def make_search_explain_tool(root_dir: Path, llm: BaseChatModel) -> BaseTool:
    """Create a ``search-explain`` tool bound to ``root_dir`` and ``llm``.

    The root directory and language model are captured in the closure at
    construction time so the tool is a plain :func:`@tool`-decorated function
    (no custom ``BaseTool`` subclass fields), which is how recent
    langchain-core expects tools to be registered.

    :param root_dir: The root directory to search in.
    :param llm: The language model instance to use for summarization.
    :return: A LangChain tool that searches the codebase and explains hits.
    """
    root = Path(root_dir).expanduser().resolve()

    @tool(
        "search-explain",
        args_schema=SearchExplainArgs,
        response_format="content_and_artifact",
        description=(
            "Search the codebase for a term or regex, then summarize matching files and snippets. "
            "Use this when the user asks to find, locate, or explain code across multiple files."
        ),
    )
    def search_explain(
        search_query: str, max_results: int = 10
    ) -> tuple[str, FileObject]:
        """Search for a string or regexp in the codebase and summarize results.

        :param search_query: Term or regexp to search.
        :param max_results: Maximum number of hits to return.
        :return: Tuple of (summary, FileObject) with the first hit's path.
        """
        # compile regex safely
        try:
            pattern = re.compile(search_query, re.IGNORECASE)
        except re.error:
            pattern = None

        hits = _gather_hits(root, search_query, pattern, max_results)

        if not hits:
            return (
                "❌ No matches found.",
                FileObject(path=Path(), contents="", status="No hits"),
            )

        summary, first_hit = _summarize_hits(llm, hits)
        file_obj = FileObject(
            path=Path(str(first_hit["file_path"])).resolve(),
            contents="",
            status="Analyzed",
        )

        return summary, file_obj

    return search_explain


def _read_ipynb_preview(path: Path) -> str:
    """Read the preview of an IPython notebook file.

    :param path: The path to the IPython notebook file.
    :return: The preview of the IPython notebook file.
    """
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
        cells = nb.get("cells", [])
        texts: list[str] = []
        for c in cells:
            if c.get("cell_type") == "markdown" or c.get("cell_type") == "code":
                texts.append("".join(c.get("source", [])))
        return "\n".join(texts)[:1000]
    except Exception:
        return ""


def _gather_hits(
    root: Path,
    search_query: str,
    pattern: re.Pattern[str] | None,
    max_results: int,
) -> list[dict[str, str]]:
    """Gather all matching files and their snippets from the root directory.

    :param root: The root directory to search in.
    :param search_query: The search query to look for in files.
    :param pattern: A compiled regex pattern to search for.
    :param max_results: The maximum number of hits to return.
    :return: A list of dictionaries, each containing the file path and snippet.
    """
    hits: list[dict[str, str]] = []
    for path in root.rglob("*"):
        if not _is_candidate_path(path):
            continue

        content = _read_file_content(path)
        if content is None:
            continue

        if pattern:
            matched = bool(pattern.search(content))
        else:
            matched = search_query.lower() in content.lower()

        if not matched:
            continue

        snippet = content[:600].replace("\n", " ")
        hits.append({"file_path": str(path), "snippet": snippet})
        if len(hits) >= max_results:
            break

    return hits


def _is_candidate_path(path: Path) -> bool:
    """Return True if the path should be considered for searching.

    Skip virtualenvs, large folders, and non-files.

    :param path: The path to check.
    :return: True if the path should be considered for searching.
    """
    if any(
        part
        in {".venv", "venv", "node_modules", "packrat", "archive", "output"}
        for part in path.parts
    ):
        return False
    if not path.is_file():
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:  # 2MB
            return False
    except Exception:
        return False
    return True


def _read_file_content(path: Path) -> str | None:
    """Read file content with safe fallback for notebooks and read errors.

    :param path: The path to the file to read.
    :return: The file content as a string, or None if there was an error.
    """
    try:
        if path.suffix == ".ipynb":
            return _read_ipynb_preview(path)
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _summarize_hits(
    llm: BaseChatModel, hits: list[dict[str, str]]
) -> tuple[str, dict[str, str]]:
    """Summarize the hits using the LLM.

    :param llm: The language model instance to use for summarization.
    :param hits: A list of dictionaries, each containing the file path and snippet.
    :return: Tuple of (summary, first_hit) from the hits.
    """
    snippets = "\n\n".join(
        f"File: {hit['file_path']}\nSnippet:\n{hit['snippet']}" for hit in hits
    )

    summary_prompt = (
        "You are an expert code analyst. Provide a comprehensive analysis of the following code snippets. "
        "Include: 1) Overall purpose and functionality, 2) Key design patterns and architectural decisions, "
        "3) Potential issues or improvements, 4) Dependencies and relationships between files, "
        "5) Best practices being followed or violated. Be thorough and detailed.\n\n"
        + snippets
    )

    response = llm.invoke([HumanMessage(content=summary_prompt)])
    if hasattr(response, "content"):
        summary: str = str(response.content)
    else:
        summary = str(response)

    return summary, hits[0]
