"""Tool to generate tests."""

from __future__ import annotations

from pathlib import Path

from berg_agents.tools._io import _atomic_write
from langchain.tools import tool
from pydantic import BaseModel, Field

class GenerateTestArgs(BaseModel):
    """Arguments for the generate-test tool.

    Attributes:
        file_path: Path to the module/file to generate tests for.
        tests_dir: Directory to place generated tests.
        root_dir: Root directory the file is relative to (optional).
    """

    file_path: str = Field(
        ..., description="Path to the module/file to generate tests for"
    )
    tests_dir: str = Field(
        "tests", description="Directory to place generated tests"
    )
    root_dir: Path | None = Field(
        None, description="Root directory the file is relative to (optional)"
    )


@tool(
    args_schema=GenerateTestArgs,
    parse_docstring=True,
    description="Generate a basic pytest test file for a given Python module.",
)
def generate_test(
    file_path: str, tests_dir: str = "tests", root_dir: Path | None = None
) -> str:
    """Generate a basic pytest test file for a given Python module.

    Creates a tests/ directory and a test_<module>.py scaffold.

    :param file_path: Path to the module/file to generate tests for.
    :param tests_dir: Directory to place generated tests.
    :param root_dir: Root directory the file is relative to (optional).
    :return: Message indicating success or failure.
    """
    if root_dir is None:
        root_dir = Path.cwd()

    src = (root_dir / file_path).resolve()
    if not src.exists():
        return f"❌ Source file not found: {src}"
    if src.suffix != ".py":
        raise ValueError(f"File {file_path} is not a Python file.")

    module_name = Path(file_path).stem
    test_file = root_dir / tests_dir / f"test_{module_name}.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)

    scaffold = f'''
import pytest

import {module_name}


def test_{module_name}_smoke():
    """Smoke test for ``{module_name}``.

    The generated module imports successfully. Replace this with meaningful
    tests for the module's public API.
    """
    assert {module_name} is not None
'''
    if test_file.exists():
        return f"❌ Test file already exists: {test_file}"

    _atomic_write(test_file, scaffold)
    return f"✅ Generated test scaffold: {test_file}"
