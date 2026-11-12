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
  source .venv/Scripts/activate 2>/dev/null || true
else
  source .venv/bin/activate 2>/dev/null || true
  export PUPPETEER_CACHE_DIR="$HOME/.cache/puppeteer"
fi
echo "Starting code visualization script..."
RAW_VISUALIZATION_DIR="$(pwd)/docs/visualizations"
PNG_DIR="$RAW_VISUALIZATION_DIR/png"
SVG_DIR="$RAW_VISUALIZATION_DIR/svg"
mkdir -p "$SVG_DIR"
mkdir -p "$PNG_DIR"
echo "▶ Running custom Python diagram extractor..."
python project_utils/generate_diagrams.py || { echo "❌ Python diagram extractor failed!"; exit 1; }
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
  if [ -f "$mermaid_file" ]; then
    bunx mermaidfmt -w "$mermaid_file" 2>/dev/null || true
  fi
done
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
  if [ -f "$mermaid_file" ]; then
    png_file="$PNG_DIR/$(basename "$mermaid_file" .mmd).png"
    echo "  ▶ Converting $mermaid_file to $png_file"
    bunx mmdc -i "$mermaid_file" -o "$png_file" -t neutral -b "#ffffff"

    # test svg in same loop
    svg_file="$SVG_DIR/$(basename "$mermaid_file" .mmd).svg"
    echo "  ▶ Converting $mermaid_file to $svg_file"
    bunx mmdc -i "$mermaid_file" -o "$svg_file" -t neutral -b "#ffffff"
  fi
done
echo "=========================================="
echo "All tasks completed successfully!"
echo "=========================================="
exit 0
