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
quarto render docs/README.qmd --to gfm --output README.md
