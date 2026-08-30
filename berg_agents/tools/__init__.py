"""Tools for the berg_agents package.

The registry exports two kinds of tools:

- function-based tools (``edit_file``, ``read_file``, ``generate_test``) which
  are :class:`langchain_core.tools.StructuredTool` instances created with the
  ``@tool`` decorator and accept ``root_dir`` at call time, and
- factory-based tools (``make_format_code_tool``, ``make_new_file_tool``, ...)
  which return ``@tool``-decorated functions with ``root_dir`` (and optionally
  an ``llm`` instance) captured in the closure at construction time.
"""

from __future__ import annotations

from berg_agents.tools.edit_file_tool import edit_file
from berg_agents.tools.format_code_tool import make_format_code_tool
from berg_agents.tools.general_chat_tool import make_general_chat_tool
from berg_agents.tools.generate_test_tool import generate_test
from berg_agents.tools.new_file_tool import make_new_file_tool
from berg_agents.tools.notebook_tool import py_to_ipynb
from berg_agents.tools.r_tool import make_r_script_tool
from berg_agents.tools.read_file_tool import read_file
from berg_agents.tools.search_explain_tool import make_search_explain_tool

__all__ = [
    "edit_file",
    "generate_test",
    "make_format_code_tool",
    "make_general_chat_tool",
    "make_new_file_tool",
    "make_r_script_tool",
    "make_search_explain_tool",
    "py_to_ipynb",
    "read_file",
]
