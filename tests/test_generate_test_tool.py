"""Unit test for the ``generate_test`` LangChain tool."""

from __future__ import annotations

import textwrap

from pathlib import Path

import pytest

from berg_agents.tools.generate_test_tool import generate_test


@pytest.fixture
def sample_py(tmp_path: Path) -> Path:
    """Create a tiny Python module that can be used as input.

    :param tmp_path: Temporary directory path from pytest.
    :return: Path to the created Python file.
    """
    file = tmp_path / "sample.py"
    file.write_text(
        textwrap.dedent("""
                            def add(a, b):
                                '''
                                Add two numbers together.

                                :param a: First number.
                                :param b: Second number.
                                :return: Sum of a and b.
                                '''
                                return a + b
                            """)
    )
    return file


def test_generate_test_tool_executes(sample_py: Path) -> None:
    """Running the tool should create a tests/ directory with a test module.

    :param sample_py: Sample python file created by the fixture.
    :raises FileNotFoundError: If the test file was not created.
    :raises AssertionError: If the expected files or content are not found.
    """
    result = generate_test.invoke({
        "file_path": str(sample_py),
        "root_dir": str(sample_py.parent),
        "tests_dir": "tests",
    })
    assert "Generated test scaffold" in result, (
        "Tool should confirm test file creation"
    )

    tests_dir = sample_py.parent / "tests"
    assert tests_dir.exists() and tests_dir.is_dir()

    test_files = list(tests_dir.glob("test_*.py"))
    assert test_files, "No test file was generated"
    assert "def test_sample_smoke" in test_files[0].read_text()


def test_generate_test_tool_invalid_file(tmp_path: Path) -> None:
    """Providing a non-Python file should raise an error.

    :param tmp_path: Temporary directory path from pytest.
    :raises ValueError: If the file is not a Python file.
    """
    non_py = tmp_path / "not_py.txt"
    non_py.write_text("just text")
    with pytest.raises(ValueError, match="is not a Python file"):
        generate_test.invoke({
            "file_path": str(non_py),
            "root_dir": str(tmp_path),
            "tests_dir": "tests",
        })
