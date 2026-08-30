"""JSONC (JSON with comments) parsing helpers.

The project uses ``bergagents.jsonc`` as its primary configuration file, so
both :func:`berg_agents.main.load_config` and the pydantic-settings source in
:mod:`berg_agents.config.settings` need a loader that understands JSONC.  The standard
:mod:`json` module rejects comments and trailing commas, so this module
provides a small, string-aware pre-processor that strips them before handing
the text to :func:`json.loads`.

The stripper is a single-pass state machine that tracks whether it is inside a
string literal, so ``//`` or ``/* */`` sequences that appear inside string
values are preserved verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

def strip_comments(text: str) -> str:
    """Remove ``//`` line comments and ``/* ... */`` block comments.

    The scan is string-aware: comment markers inside double-quoted strings are
    left untouched.  Trailing commas before ``}`` or ``]`` are also removed,
    which is a common JSONC convenience.

    :param text: Raw JSONC document text.
    :returns: The text with comments and trailing commas removed.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_string:
            out.append(ch)
            if ch == "\\":  # escaped char: copy it and the next char verbatim
                if i + 1 < n:
                    out.append(nxt)
                    i += 1
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":  # line comment -> skip to end of line
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if ch == "/" and nxt == "*":  # block comment -> skip to closing */
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2  # consume the closing "*/"
            continue

        if ch == ",":  # trailing comma before } or ] -> drop it
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def loads(text: str) -> Any:
    """Parse a JSONC document string into a Python object.

    :param text: JSONC document text.
    :returns: The parsed object (typically a ``dict``).
    :raises json.JSONDecodeError: If the cleaned text is not valid JSON.
    """
    return json.loads(strip_comments(text))


def load(path: str | Path) -> Any:
    """Parse a JSONC file into a Python object.

    :param path: Path to the JSONC file.
    :returns: The parsed object (typically a ``dict``).
    :raises json.JSONDecodeError: If the file content is not valid JSONC.
    """
    with Path(path).open("r", encoding="utf-8") as f:
        return loads(f.read())
