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
uv run pydoctor -c pydoctor.ini >pydoctor.txt
echo "Deleting apidocs/index.html to avoid redirect issues..."
rm -f apidocs/index.html
echo "Creating redirect from apidocs/index.html to berg_agents.html..."
echo '<meta http-equiv="refresh" content="0; url=berg_agents.html">' >apidocs/index.html
echo "Deploying API docs to Quarto site output directory..."
rm -rf docs/docs_web/apidocs
mkdir -p docs/docs_web/apidocs
cp -rL apidocs/* docs/docs_web/apidocs/
echo ""
echo "============================================"
