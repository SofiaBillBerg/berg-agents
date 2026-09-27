#!/usr/bin/env bash

# Avbryt direkt om ett kritiskt kommando misslyckas, men tillåt kontroller
set -e
set -o pipefail

# Kolla om användaren skickade med --auto eller -a flaggan
AUTO_MODE=false
if [[ "$1" == "--auto" || "$1" == "-a" ]]; then
	AUTO_MODE=true
fi

# 1. Hitta projektets rot dynamiskt baserat på skriptets placering
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "🚀 Starting Berg Agents Web Application"
echo "=========================================="

# 2. OS-agnostisk aktivering av virtuell miljö
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

# Funktion för att hitta nästa lediga port automatiskt med Python
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

# 3. Smart, informativ och interaktiv porthantering
TARGET_PORT=8001

check_and_select_port() {
	local port=$1
	if lsof -i :$port >/dev/null 2>&1; then
		# Hämta information om processen som använder porten
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

# 4. Installera och bygg frontend (Next.js)
UI_DIR="$PROJECT_ROOT/berg_agents/ui/webapp"
if [ -d "$UI_DIR" ]; then
	echo "▶ Building frontend in $UI_DIR..."
	cd "$UI_DIR"
	bun install || {
		echo "❌ 'bun install' failed"
		exit 1
	}
	bun run next build || {
		echo "❌ 'bun run next build' failed"
		exit 1
	}
	cd "$PROJECT_ROOT"
else
	echo "❌ Frontend directory not found at $UI_DIR"
	exit 1
fi

# 5. Installera Python-beroenden i editerbart läge
echo "▶ Syncing Python packages..."
uv pip install -e . || {
	echo "❌ Python package installation failed"
	exit 1
}

# 6. Starta applikationen
echo "=========================================="
echo "🎯 Success! Launching app on port $bergport..."
echo "=========================================="

uv run -m berg_agents --web --port $bergport
