"""R script execution tool."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

class RScriptArgs(BaseModel):
    """Arguments for executing an R script.

    Attributes:
        code: The R code to be executed.
    """

    code: str = Field(..., description="The R code to be executed.")


def make_r_script_tool() -> BaseTool:
    """Create an ``r-script`` tool for executing R code.

    The tool is a plain :func:`@tool`-decorated function (no custom
    ``BaseTool`` subclass fields), which is how recent langchain-core expects
    tools to be registered.

    :return: A LangChain tool that executes R code.
    """

    @tool(
        "r-script",
        args_schema=RScriptArgs,
        description=(
            "Use this tool to execute R code. "
            "Provide the R code as a string. The tool will return the standard output and standard error."
        ),
    )
    def r_script(code: str) -> str:
        """Execute the given R code and return its output.

        :param code: The R code to be executed.
        :return: The output of the R script execution.
        """
        with tempfile.NamedTemporaryFile(
            encoding="utf-8", mode="w", suffix=".R", delete=False
        ) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        try:  # ruff: ignore [too-many-statements-in-try-clause]
            result = subprocess.run(
                ["Rscript", temp_file_path],
                capture_output=True,
                text=True,
                check=False,
                # Do not raise exception on non-zero exit code
            )

            output = ""
            if result.stdout:
                output += f"--- STDOUT ---\n{result.stdout}\n"
            if result.stderr:
                output += f"--- STDERR ---\n{result.stderr}\n"

            if not output:
                return "✅ R script executed with no output."

            return output

        except FileNotFoundError:
            return "❌ Error: 'Rscript' command not found. Please ensure R is installed and in your system's PATH."
        except Exception as e:
            return f"❌ An unexpected error occurred while running the R script: {e}"
        finally:
            # Clean up the temporary file
            Path(temp_file_path).unlink()

    return r_script
