#!/usr/bin/env bash
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

# ==============================================================================
# HOW TO USE LOCAL_ONLY TAGS:
#
# MARKDOWN / QUARTO (.md, .qmd):
#
#
# PYTHON / TOML / GITIGNORE (.py, .toml, .gitignore):
#
#
# JAVASCRIPT / TYPESCRIPT (.js, .ts):
#
#
# YAML (.yml):
#
#
# JSON (.json):
# {
#   "api_url": "https://production.com",
#   : ""
# }
# ==============================================================================

# 1. Update .gitattributes for all target file types
EXTENSIONS=("*.md" "*.qmd" "*.py" "*.toml" ".gitignore" "*.js" "*.ts" "*.jsx" "*.tsx" "*.yml" "*.yaml" "*.json")

for ext in "${EXTENSIONS[@]}"; do
  if ! grep -q "$ext filter=strip-local" .gitattributes 2>/dev/null; then
    echo "$ext filter=strip-local" >>.gitattributes
    echo "Added filter for $ext to .gitattributes"
  fi
done
# 2. Configure Git clean filter to strip local blocks before staging
git config filter.strip-local.clean "$(
  cat <<'EOF'
python3 -c '
import sys, re
content = sys.stdin.read()
pattern = re.compile(r"\s*(|# LOCAL_ONLY_END|// LOCAL_ONLY_END|\"LOCAL_ONLY_END\")\s*", re.DOTALL)
sys.stdout.write(pattern.sub("\n", content))
'
EOF
)"

# 3. Configure Git smudge filter
git config filter.strip-local.smudge "cat"

echo "Git filter for 'LOCAL_ONLY' content is successfully configured."
