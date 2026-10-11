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
uv run pydoctor -c pydoctor.ini
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
