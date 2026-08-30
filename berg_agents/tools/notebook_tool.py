"""Tool to generate notebooks."""

from __future__ import annotations

from pathlib import Path

from berg_agents.exceptions import CodeAgentError
import nbformat

def py_to_ipynb(  # ruff: ignore[complex-structure]
    py_file: Path,
    output_path: Path | None = None,
    content: str = "",
    mode: str = "create",
) -> Path:  # ruff: ignore[complex-structure]
    """Convert a Python script to a minimal Jupyter notebook.

    The function searches the script for ``# %%`` markers - any text
    following a marker until the next marker (or the file end) becomes a
    separate cell.  If no markers are found, the entire file becomes a
    single cell.

    :param content:
    :param py_file: Path to the input Python file.
    :param output_path: Destination notebook path.  If omitted, ``py_file`` is
        rewritten with a ``.ipynb`` extension.
    :param mode: Mode: create|append|replace.
    :return: Absolute path to the generated notebook.
    """
    if nbformat is None:
        raise CodeAgentError(
            "nbformat is not installed; please install it to use the notebook tool"
        )

    mode = mode.lower()
    py_file = Path(py_file).expanduser().resolve()
    if not py_file.is_file():
        raise CodeAgentError(f"Python file {py_file!s} does not exist")
    if mode not in {"create", "append", "replace"}:
        raise CodeAgentError(f"Unknown mode: {mode!s}")
    if mode == "append" and not py_file.with_suffix(".ipynb").exists():
        raise CodeAgentError(
            f"Cannot append to notebook {py_file.with_suffix('.ipynb')!s} because it does not exist"
        )
    if mode == "replace":
        # Interpret content as raw notebook JSON or as a Markdown cell
        try:
            nb_obj = nbformat.reads(content, as_version=4)
            if output_path is None:
                output_path = py_file.with_suffix(".ipynb")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            nbformat.write(nb_obj, str(output_path))
            return output_path
        except Exception as e:
            raise CodeAgentError(
                f"Error occurred while replacing notebook: {e}"
            )
    if mode == "create" and py_file.with_suffix(".ipynb").exists():
        raise CodeAgentError(
            f"Cannot create notebook {py_file.with_suffix('.ipynb')!s} because it already exists"
        )
    if mode == "append":
        nb = nbformat.read(str(py_file.with_suffix(".ipynb")), as_version=4)
    else:
        nb = nbformat.v4.new_notebook()
        current_cell_lines: list[str] = []
        with py_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == "# %%":
                    if current_cell_lines:
                        nb.cells.append(
                            nbformat.v4.new_code_cell(
                                source="".join(current_cell_lines)
                            )
                        )
                        current_cell_lines = []
                else:
                    current_cell_lines.append(line)
            if current_cell_lines:
                nb.cells.append(
                    nbformat.v4.new_code_cell(
                        source="".join(current_cell_lines)
                    )
                )
    if content:
        nb.cells.append(nbformat.v4.new_markdown_cell(content))
    if output_path is None:
        output_path = py_file.with_suffix(".ipynb")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, str(output_path))
    return output_path
