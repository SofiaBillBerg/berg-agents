"""Check agent output for issues."""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import re
import sys

from pathlib import Path


REVIEW_PATH = Path(".ci/llm_review.txt")

if not REVIEW_PATH.exists():
    print("❌ No review file found")
    sys.exit(1)

REVIEW = REVIEW_PATH.read_text(encoding="utf-8")

# Check for issues
if re.search(r"❌|problem|bug|error|security", REVIEW, re.IGNORECASE):
    print("❌ Agent flagged potential issues:")
    print(REVIEW)
    sys.exit(1)
else:
    print("✅ Review passed")
    print(REVIEW)
    sys.exit(0)
