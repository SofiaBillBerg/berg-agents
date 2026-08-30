set -euo pipefail
if ! command -v quarto >/dev/null 2>&1;then
echo "Quarto not found in PATH. Install Quarto." >&2
else
echo "Building Quarto site to docs/docs_web..."
quarto render
echo "Quarto site built to docs/docs_web"
quarto render docs/README.qmd --to gfm --output README.md
echo "README.md generated"
fi
