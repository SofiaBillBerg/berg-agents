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

set +e
set -o pipefail
echo "Activating virtual environment..."
if [[ $OSTYPE == "msys" || $OSTYPE == "win32" || $OSTYPE == "cygwin" ]]; then
  if [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
  else
    echo "✗ Could not find .venv/Scripts/activate"
  fi
else
  if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
  else
    echo "✗ Could not find .venv/bin/activate"
  fi
fi
FAILURES=()
run_step() {
  local label="$1"
  shift
  echo ""
  echo "▶ $label"
  if "$@"; then
    echo "  ✓ $label passed"
  else
    local code=$?
    echo "  ✗ $label failed (exit $code) - continuing..."
    FAILURES+=("$label (exit $code)")
  fi
}
echo "Starting code quality script..."
echo "Current working directory: $(pwd)"
echo "Creating output directories..."
CODE_QUALITY_DIR="$(pwd)/.code_quality_outputs"
mkdir -p "$CODE_QUALITY_DIR" stubs
echo "Output directories created: $CODE_QUALITY_DIR"
run_step "coverage run" coverage run --context=test --source=berg_agents -m pytest tests/ --cov-report lcov --cov-report=term-missing --cov-report markdown:"$CODE_QUALITY_DIR/cov.md" --color=yes --tb=short --junitxml="$CODE_QUALITY_DIR/pytest_report.xml"
echo ""
echo "============================================"
if [ ${#FAILURES[@]} -eq 0 ]; then
  echo "Test completed"
  exit 0
else
  echo "Completed with ${#FAILURES[@]} failure(s):"
  for f in "${FAILURES[@]}"; do
    echo "   ✗ $f"
  done
  echo ""
  echo "You can review errors above and decide which to fix, saved to $CODE_QUALITY_DIR/pytest_report.xml and $CODE_QUALITY_DIR/cov.md"
  echo "============================================"
  exit 0
fi
