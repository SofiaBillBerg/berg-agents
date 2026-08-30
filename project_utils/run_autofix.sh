#!/bin/bash
set +e
set -o pipefail
echo "Activating virtual environment..."
if [[ $OSTYPE == "msys" || $OSTYPE == "win32" || $OSTYPE == "cygwin" ]];then
if [ -f ".venv/Scripts/activate" ];then
source .venv/Scripts/activate
else
echo "✗ Could not find .venv/Scripts/activate"
fi
else
if [ -f ".venv/bin/activate" ];then
source .venv/bin/activate
else
echo "✗ Could not find .venv/bin/activate"
fi
fi
FAILURES=()
run_step(){
local label="$1"
shift
echo ""
echo "▶ $label"
if "$@";then
echo "  ✓ $label passed"
else
local code=$?
echo "  ✗ $label failed (exit $code) - continuing..."
FAILURES+=("$label (exit $code)")
fi
}
echo "Starting code quality and visualization script..."
echo "Current working directory: $(pwd)"
echo "Creating output directories..."
mkdir -p .code_quality_outputs
CODE_QUALITY_DIR=".code_quality_outputs"
echo "Output directories created: $CODE_QUALITY_DIR"
run_step "uv format" uv format --preview-features format-command
run_step "isort" uv run isort . --overwrite-in-place --dedup-headings -s stubs --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv run ruff format
run_step "pyrefly check" uv run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --color=always --python-interpreter-path .venv/bin/python3 --output=$CODE_QUALITY_DIR/pyrefly_report.txt||true
run_step "uv pip install -e ." uv pip install -e .
echo ""
echo "============================================"
if [ ${#FAILURES[@]} -eq 0 ];then
echo "All tasks completed successfully!"
exit 0
else
echo "⚠  Completed with ${#FAILURES[@]} failure(s):"
for f in "${FAILURES[@]}";do
echo "   ✗ $f"
done
echo ""
echo "You can review errors above and decide which to fix, saved to $CODE_QUALITY_DIR/pyrefly_report.txt"
echo "============================================"
exit 0
fi
