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
mkdir -p stubs
CODE_QUALITY_DIR=".code_quality_outputs"
echo "Output directories created: $CODE_QUALITY_DIR, stubs"
run_step "uv format" uv format --preview-features format-command
run_step "isort" uv run isort . --float-to-top --sp pyproject.toml --gitignore
run_step "ruff format" uv run ruff format
run_step "pytest" uv run pytest --color=yes --tb=short --junitxml="$CODE_QUALITY_DIR"/pytest_report.xml --html="$CODE_QUALITY_DIR"/pytest_report.html --self-contained-html
run_step "pyrefly check" uv run pyrefly check --remove-unused-ignores --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --summary=full --dependency-graph="$CODE_QUALITY_DIR"/pyrefly_deps_graph.json --color=always --python-interpreter-path .venv/bin/python3 --verbose --output=.code_quality_outputs/pyrefly_report.txt
run_step "pyrefly stubgen" uv run pyrefly stubgen --output-dir ./stubs --include-docstrings --include-private --check-unannotated-defs=true --infer-return-types=checked --use-ignore-files=true --verbose --color=always --config pyproject.toml --permissive-ignores=true
run_step "pyanalyze" uv run pyanalyze --config-file pyproject.toml --find-unused --find-unused-attributes --markdown-output="$CODE_QUALITY_DIR"/pyanalyze_reports_0.md --verbose --enable-all
run_step "pytype" uv run pytype berg_agents --config pyproject.toml -v 2 --use-fiddle-overlay --precise-return --protocols --overriding-renamed-parameter-count-checks --unresolved
run_step "flake8" uv run flake8 berg_agents --show-source --verbose --extend-exclude "_build, .venv, *cache*, node_modules, dist, build, .ipynb_checkpoints, *support-libs" --enable-extensions pycodestyle --format=pylint --max-line-length 80 --output-file "$CODE_QUALITY_DIR"/flake_report.txt --max-doc-length 100 --statistics --tee --color always --count --doctests
echo ""
run_step "pip install -e ." uv pip install -e .
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
echo "You can review errors above and decide which to fix."
echo "============================================"
exit 0
fi
