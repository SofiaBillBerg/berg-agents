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

# Fail the script on any error and treat unset variables as an error
set -e
set -o pipefail

# Check if user specified --auto or -a flag
AUTO_MODE=false
if [[ "$1" == "--auto" || "$1" == "-a" ]]; then
        AUTO_MODE=true
fi

# 1. Find the project root directory and change to it
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "🚀 Starting Berg Agents Web Application"
echo "=========================================="

# 2. OS detection and virtual environment activation
echo "▶ Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || "$OSTYPE" == "cygwin" ]]; then
        source .venv/Scripts/activate 2>/dev/null || {
                echo "❌ Failed to activate .venv on Windows"
                exit 1
        }
else
        source .venv/bin/activate 2>/dev/null || {
                echo "❌ Failed to activate .venv on Unix"
                exit 1
        }
fi

# 3. Find a free port
find_free_port() {
        local start_port=$1
        python3 -c "
import socket
port = $start_port
while True:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            print(port)
            break
    except OSError:
        port += 1
"
}

# 3. Check if the default port 8001 is free, if not, find a free port
TARGET_PORT=8001

check_and_select_port() {
        local port=$1
        if lsof -i :$port >/dev/null 2>&1; then
                # If the port is busy, get the process info
                local proc_info
                proc_info=$(lsof -i :$port -sTCP:LISTEN -t | xargs ps -o pid,comm= -p 2>/dev/null | awk '{print "PID: " $1 " (" $2 ")"}')
                [ -z "$proc_info" ] && proc_info="Unknown process"

                if [ "$AUTO_MODE" = true ]; then
                        echo "⚠️ Port $port is BUSY by: $proc_info"
                        echo "▶ [--auto mode] Searching for a free port automatically..."
                        TARGET_PORT=$(find_free_port 8001)
                        echo "✅ Found a free port: $TARGET_PORT"
                        return
                fi

                echo "⚠️ Port $port is BUSY by: $proc_info"
                echo "What would you like to do?"
                echo "1) Kill that process and use port $port"
                echo "2) Automatically find the next available free port"
                echo "3) Enter a custom port manually"
                echo "4) Abort everything"

                read -r -p "Select an option [1-4]: " choice

                case $choice in
                1)
                        echo "▶ Killing process on port $port..."
                        kill -9 $(lsof -t -i :$port) 2>/dev/null || true
                        TARGET_PORT=$port
                        ;;
                2)
                        echo "▶ Searching for a free port..."
                        TARGET_PORT=$(find_free_port 8001)
                        echo "✅ Found a free port: $TARGET_PORT"
                        ;;
                3)
                        read -r -p "Enter your custom port: " custom_port
                        TARGET_PORT=$custom_port
                        check_and_select_port $custom_port
                        ;;
                *)
                        echo "❌ Operation aborted by user."
                        exit 1
                        ;;
                esac
        else
                echo "✅ Port $port is FREE!"
                TARGET_PORT=$port
        fi
}

echo "▶ Checking available ports..."
check_and_select_port 8001
export bergport=$TARGET_PORT

# 4. Install and build frontend (Next.js)
UI_DIR="$PROJECT_ROOT/berg_agents/ui/webapp"
if [ -d "$UI_DIR" ]; then
        echo "▶ Building frontend in $UI_DIR..."
        cd "$UI_DIR"
        bun install || {
                echo "❌ 'bun install' failed"
                exit 1
        }
        # BERG_BACKEND_URL is baked into the build as the proxy destination, so
        # it must name the port chosen above — passing it only to `next start`
        # would have no effect (verified: a bogus value at run time still hit
        # the baked one).
        BERG_BACKEND_URL="http://127.0.0.1:$bergport" bun run next build || {
                echo "❌ 'bun run next build' failed"
                exit 1
        }
        cd "$PROJECT_ROOT"
else
        echo "❌ Frontend directory not found at $UI_DIR"
        exit 1
fi

# 5. Install Python dependencies in editable mode
echo "▶ Syncing Python packages..."
uv pip install -e . || {
        echo "❌ Python package installation failed"
        exit 1
}

# 6. Build Shared-ToDo package
echo "▶ Building Shared-ToDo package..."
cd berg_plugins/shared-todo && bun run build:ui || {
        echo "❌ Shared-ToDo package ui build failed"
        exit 1
}

# 7. Build Shared-ToDo package
echo "▶ Building Shared-ToDo package..."
uv build || {
        echo "❌ Shared-ToDo package build failed"
        exit 1
}

# 8. Build Berg-Agents package
echo "▶ Building Berg-Agents package..."
cd $PROJECT_ROOT && uv build || {
        echo "❌ Berg-Agents package build failed"
        exit 1
}
# 9. Start the application.
#
# TWO processes now, not one. The UI used to be a static export mounted by
# FastAPI on the backend's own port; it is a real Next server since the
# orchestrator arrived (the Workflow runtime needs server routes), so Next has
# to be started alongside Python. The UI proxies /api/* to the backend, so the
# backend URL has to match the port chosen above — and because Next bakes that
# destination into the build, the build in step 4 must use the same value.
UI_PORT="${BERG_UI_PORT:-3100}"

echo "=========================================="
echo "🎯 Success! Launching app"
echo "   backend : http://localhost:$bergport"
echo "   UI      : http://localhost:$UI_PORT"
echo "=========================================="

# Start the UI first in the background so the browser finds it already warm.
(
        cd "$PROJECT_ROOT/berg_agents/ui/webapp" &&
                bun next start -p "$UI_PORT"
) &
UI_PID=$!

# Stop the UI when this script is interrupted, so Ctrl-C does not leave an
# orphaned Next server holding the port.
trap 'kill "$UI_PID" 2>/dev/null || true' INT TERM EXIT

uv run -m berg_agents --web --port "$bergport" --debug --log-level=info --hot-reload
