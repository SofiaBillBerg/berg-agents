#!/usr/bin/env bash
#
# <one line to give the program's name and a brief idea of what it does.>
#
# Copyright (c) 2026.
#         Copyright (C) <year>  <name of author>
#
#         This program is free software: you can redistribute it and/or modify
#         it under the terms of the GNU Affero General Public License as
#         published by the Free Software Foundation, either version 3 of the
#         License, or (at your option) any later version.
#
#         This program is distributed in the hope that it will be useful,
#         but WITHOUT ANY WARRANTY; without even the implied warranty of
#         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#         GNU Affero General Public License for more details.
#
#         You should have received a copy of the GNU Affero General Public License
#         along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
#

set +e
set -o pipefail
echo "Activating virtual environment..."
if [[ $OSTYPE == "msys" || $OSTYPE == "win32" || $OSTYPE == "cygwin" ]]; then
	source .venv/Scripts/activate 2>/dev/null || true
else
	source .venv/bin/activate 2>/dev/null || true
fi
echo "Starting code visualization script..."
RAW_VISUALIZATION_DIR="$(pwd)/docs/visualizations"
SVG_DIR="$RAW_VISUALIZATION_DIR/png" #svg"
mkdir -p "$SVG_DIR"
echo "▶ Running custom Python diagram extractor..."
python project_utils/generate_diagrams.py
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
	if [ -f "$mermaid_file" ]; then
		bunx mermaidfmt -w "$mermaid_file" 2>/dev/null || true
	fi
done
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
	if [ -f "$mermaid_file" ]; then
		svg_file="$SVG_DIR/$(basename "$mermaid_file" .mmd).png" #svg"
		echo "  ▶ Converting $mermaid_file to $svg_file"
		bunx mmdc -i "$mermaid_file" -o "$svg_file" -t neutral -b "#ffffff"
	fi
done
echo "=========================================="
echo "All tasks completed successfully!"
echo "=========================================="
exit 0
