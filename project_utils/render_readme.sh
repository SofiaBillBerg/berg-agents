#!/usr/bin/env bash
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
# copy rendered docs/docs_web/docs/README.md to root README.md and fix links where prefixed with ../
#echo "Copying README.md..."
#cp docs/docs_web/docs/README.md README.md
#echo "Fixing links in README.md..."
#sed -i.bak 's|\.\./||g' README.md
#rm README.md.bak
#echo "README.md copied and links fixed."

echo "Converting docs/README.qmd to README.md with quarto pandoc"
quarto pandoc docs/README.qmd --to github_document README.md
# Fix links with ../ in the README.md
echo "Fixing links in README.md..."
sed -i.bak 's|\.\./||g' README.md
rm README.md.bak
echo "Links in README.md fixed."
