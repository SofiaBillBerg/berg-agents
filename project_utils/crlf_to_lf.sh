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

echo "Configuring Git to handle line endings..."
if ! git config --global core.eol | grep -q "lf"; then
  git config --global core.eol lf
fi
if ! git config --global core.autocrlf | grep -q "input"; then
  git config --global core.autocrlf input
fi
echo "Git configuration complete."
echo "Creating or updating .gitattributes to enforce LF line endings..."
if [ ! -f .gitattributes ]; then
  echo "* text=auto eol=lf" >.gitattributes
  echo ".gitattributes file created."
else
  if ! grep -q "text=auto eol=lf" .gitattributes; then
    echo "* text=auto eol=lf" >>.gitattributes
    echo ".gitattributes file updated."
  else
    echo ".gitattributes file already contains the required settings."
  fi
fi
echo "Converting CRLF to LF in all text files, excluding .git directory, bat files, and binary files..."
find . -type f ! -path '*/.git/*' ! -name '*.bat' ! -name '*.bin' ! -path '*/lib/*' ! -path '*/dist/*' ! -path '*/win/*' ! -path '*/node_modules/*' | while read -r file; do
  if file "$file" | grep -q text; then
    sed -i 's/\r$//' "$file"
    echo "Converted line endings in: $file"
  fi
done
