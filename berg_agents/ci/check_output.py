"""Check agent output for issues."""

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
