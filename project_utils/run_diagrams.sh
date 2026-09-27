#!/usr/bin/env bash 
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
SVG_DIR="$RAW_VISUALIZATION_DIR/png"  #svg"
mkdir -p "$SVG_DIR"
echo "▶ Running custom Python diagram extractor..."
python project_utils/generate_diagrams.py
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
	if [ -f "$mermaid_file" ]; then
		mermaidfmt -w "$mermaid_file" 2>/dev/null || true
	fi
done
for mermaid_file in "$RAW_VISUALIZATION_DIR"/*.mmd; do
	if [ -f "$mermaid_file" ]; then
		svg_file="$SVG_DIR/$(basename "$mermaid_file" .mmd).png" #svg"
		echo "  ▶ Converting $mermaid_file to $svg_file"
		mmdc -i "$mermaid_file" -o "$svg_file" -t neutral -b "#ffffff"
	fi
done
echo "=========================================="
echo "All tasks completed successfully!"
echo "=========================================="
exit 0
