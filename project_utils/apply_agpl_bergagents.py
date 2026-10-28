# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Project utility to apply AGPLv3 license headers to source files in a directory tree."""

import os
import pathlib


AGPL_TEXT = (
    "Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. \n"
    "The system follows a harness-based execution model with multiple specialized agents working together.\n\n"
    "Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>\n\n"
    "This program is free software: you can redistribute it and/or modify\n\n"
    "it under the terms of the GNU Affero General Public License as\n"
    "published by the Free Software Foundation, either version 3 of the\n"
    "License, or (at your option) any later version.\n\n"
    "This program is distributed in the hope that it will be useful,\n"
    "but WITHOUT ANY WARRANTY; without even the implied warranty of\n"
    "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the\n"
    "GNU Affero General Public License for more details.\n\n"
    "You should have received a copy of the GNU Affero General Public License\n"
    "along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>."
)

EXCLUDED_DIRS = {
    "node_modules",
    ".next",
    ".venv",
    "venv",
    ".git",
    "dist",
    "build"}


def get_commented_header(extension):
    """Get the AGPLv3 header formatted as a comment for the given file extension.

    :param extension:  File extension (e.g., '.py', '.js', '.ts', etc.)
    :return:  String containing the commented AGPLv3 header or None if the extension is not supported.
    """
    if extension in {".ts", ".css", ".js", ".tsx", ".jsx", ".mjs"}:
        lines = [f" * {line}".rstrip() for line in AGPL_TEXT.split("\n")]
        return "/*\n" + "\n".join(lines) + "\n */\n\n"
    elif extension in {".py", ".sh"}:
        lines = [f"# {line}".rstrip() for line in AGPL_TEXT.split("\n")]
        return "\n".join(lines) + "\n\n"
    return None


def main() -> None:
    """Main function to traverse the directory tree and add AGPLv3 headers to source files."""
    processed_count = 0

    for root, dirs, files in os.walk("."):
        # Modify dirs in-place to drop explicit exclusions AND any dot-directories (.*)
        dirs[:] = [
            d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]

        for file in files:
            _, ext = os.path.splitext(file)
            header = get_commented_header(ext.lower())

            if not header:
                continue

            file_path = os.path.join(root, file)

            try:
                with pathlib.Path(file_path).open(
                    "r", encoding="utf-8", errors="ignore"
                ) as f:
                    content = f.read()

                if "GNU Affero General Public License" not in content:
                    with pathlib.Path(file_path).open(
                        "w", encoding="utf-8"
                    ) as f:
                        f.write(header + content)
                    print(f"Added AGPLv3 header to: {file_path}")
                    processed_count += 1
            except Exception as e:
                print(f"Error processing {file_path}: {e}")

    print(f"Execution completed. Successfully updated {processed_count} files.")


if __name__ == "__main__":
    main()
