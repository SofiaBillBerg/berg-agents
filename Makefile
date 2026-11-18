SHELL := $(SHELL)
.SHELLFLAGS := -c

# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html

# Makefile for Berg-Agents project, providing targets for installing dependencies and building
# the berg-agents package through bun and uv.

# ======= Berg-Agents package targets =======
# Where the Python backend listens, and therefore where the UI proxies every
# non-Next /api/* call. This is BAKED INTO THE UI BUILD, not read at run time:
# Next freezes it into dist/routes-manifest.json as the rewrite destination
# (verified 2026-11-12 — starting with a bogus value still hit :8001). So it is
# exported here, before `next build`, and every run target uses the same number.
BERG_BACKEND_PORT ?= 8001
BERG_BACKEND_URL := http://127.0.0.1:$(BERG_BACKEND_PORT)
# Where the UI is served. The UI is no longer mounted by FastAPI (its static
# export is gone), so Next needs its own port; users open this one.
BERG_UI_PORT ?= 3100

# ======= Berg's own PostgreSQL (the orchestrator's durable world) =======
#
# The TS orchestrator stores its runs events and streams in PostgreSQL via
# `@workflow/world-postgres` (see workflow-data-dir.mjs). It is BERG'S OWN
# cluster — never hindsight's, never the system postgres — because coupling
# berg's durability to another service's database would make that service's
# migrations a berg outage.
#
# World credentials, matching the world-postgres default so no config is
# needed: postgres://world:world@localhost:5434/world
BERG_PG_PORT ?= 5434
BERG_PG_DIR ?= .berg-agents/postgres
BERG_PG_BIN ?= /usr/lib/postgresql/16/bin
# $(TMPDIR) is unset under make, so the log and socket paths collapsed to
# /berg-postgres.log and refused to start. Give them a make-local default.
# Absolute: postgres resolves `unix_socket_directories` against its DATA
# directory, not the shell's CWD, so a relative path never lands where the
# server can write its lock file (verified: FATAL could not create lock file).
BERG_PG_TMP ?= $(CURDIR)/.berg-agents/postgres/run

# postgres-init: create the cluster on first run (idempotent — existing data
# is left alone), so `make run-berg-agents-web` works on a clean checkout.
postgres-init: ## Create berg's PostgreSQL cluster if it does not exist
	@if [ -f "$(BERG_PG_DIR)/PG_VERSION" ]; then \
		echo "PostgreSQL cluster already exists at $(BERG_PG_DIR)"; \
	else \
		echo "Creating PostgreSQL cluster at $(BERG_PG_DIR)"; \
		mkdir -p "$(BERG_PG_DIR)"; \
		$(BERG_PG_BIN)/initdb -D "$(BERG_PG_DIR)" -U postgres --auth=trust --encoding=UTF8 >/dev/null && \
		echo "Cluster created"; \
	fi
	@mkdir -p "$(BERG_PG_TMP)"

postgres-start: postgres-init ## Start berg's PostgreSQL (skipped if already listening)
	@# The socket directory must exist before the server starts: postgres writes
	@# .s.PGSQL.<port>.lock there and refuses to boot otherwise (verified: the
	@# server FATALed on a missing lock file when this ran after pg_ctl).
	@mkdir -p "$(BERG_PG_TMP)"
	@if ss -ltn 2>/dev/null | grep -q ":$(BERG_PG_PORT) "; then \
		echo "PostgreSQL already listening on :$(BERG_PG_PORT)"; \
	else \
		echo "Starting PostgreSQL on :$(BERG_PG_PORT)"; \
		$(BERG_PG_BIN)/pg_ctl -D "$(BERG_PG_DIR)" \
			-o "-p $(BERG_PG_PORT) -c listen_addresses=127.0.0.1 -c unix_socket_directories=$(BERG_PG_TMP)" \
			-l "$(BERG_PG_TMP)/postgres.log" start >/dev/null; \
		$(BERG_PG_BIN)/pg_isready -h 127.0.0.1 -p $(BERG_PG_PORT) || { tail -5 "$(BERG_PG_TMP)/postgres.log"; exit 1; }; \
	fi
	@# Idempotent: safe on every run, and required before the world's first run.
	@# `-tAc "select 1"` matters: psql without -c opens an interactive session,
	@# and its prompt is discarded below, so on a terminal it blocks forever
	@# waiting for input — the run target then looks like it stops right after
	@# PostgreSQL starts, with nothing after it.
	@psql "postgres://world:world@localhost:$(BERG_PG_PORT)/world" -tAc "select 1" >/dev/null 2>&1 || \
		(echo "Creating role/database world"; \
		 psql -h 127.0.0.1 -p $(BERG_PG_PORT) -U postgres -d postgres -c "CREATE ROLE world LOGIN PASSWORD 'world';" >/dev/null; \
		 psql -h 127.0.0.1 -p $(BERG_PG_PORT) -U postgres -d postgres -c "CREATE DATABASE world OWNER world;" >/dev/null)
	@# Output stays visible on purpose: `>/dev/null 2>&1 && echo` aborts the
	@# target with no clue why when the bootstrap fails. It is idempotent, so a
	@# warm run prints only its short progress lines.
	@if cd berg_agents/ui/webapp && WORKFLOW_POSTGRES_URL="postgres://world:world@localhost:$(BERG_PG_PORT)/world" \
		bunx --package @workflow/world-postgres bootstrap; then \
		echo "Workflow tables ready"; \
	else \
		echo "Workflow table bootstrap FAILED — the orchestrator has no durable world until this succeeds"; \
		exit 1; \
	fi

postgres-stop: ## Stop berg's PostgreSQL
	@if [ -f "$(BERG_PG_DIR)/postmaster.pid" ]; then \
		$(BERG_PG_BIN)/pg_ctl -D "$(BERG_PG_DIR)" stop -m fast; \
	else \
		echo "PostgreSQL not running"; \
	fi

bun-install: ## Install bun dependencies for Berg-Agents UI
	@echo "Installing bun dependencies"
	@bun install --cwd berg_agents/ui/webapp/

build-ui: bun-install ## Use bun to build the frontend for Berg-Agents UI
	@echo "Building Berg-Agents UI (proxying /api/* to $(BERG_BACKEND_URL))"
	@BERG_BACKEND_URL=$(BERG_BACKEND_URL) bun --cwd berg_agents/ui/webapp next build
	@$(MAKE) --no-print-directory record-ui-port

#: Where the UI build records the backend port its proxy destination was baked
#: with. `next start` reads that destination from the build rather than from the
#: environment (verified: exporting a different BERG_BACKEND_URL at run time
#: changes nothing), so a build made for one port keeps proxying to it after
#: another port is configured — the UI then reports ECONNREFUSED against a port
#: nothing listens on. This file is the record that lets run-ui notice.
UI_BUILD_PORT_FILE := berg_agents/ui/webapp/.next/berg-backend-port

record-ui-port: ## Record which backend port the UI build proxies to
	@# After the build, never before: the record lives inside .next, which a
	@# build may replace. Both entry points build the UI (this Makefile and
	@# install_and_run.sh), so the recording is one target they both call.
	@if [ ! -d berg_agents/ui/webapp/.next ]; then \
		echo "No .next to record — run 'make build-ui' first"; exit 1; \
	fi
	@printf '%s\n' "$(BERG_BACKEND_PORT)" > "$(UI_BUILD_PORT_FILE)"
	@echo "Recorded: this build proxies /api/* to :$(BERG_BACKEND_PORT)"


tsc-lint:  ## Use bun to lint the Berg-Agents UI
	@echo "Linting Berg-Agents UI"
	@bunx --cwd berg_agents/ui/webapp/   tsc --project /home/sofiabillberg/code-projects/berg-agents/berg_agents/ui/webapp/tsconfig.json  --noEmit --skipLibCheck
#
#eslint-fix: ## Use bun to fix eslint issues in the Berg-Agents UI
#	@echo "Fixing eslint issues in the Berg-Agents UI"
#	@cd berg_agents/ui/webapp && bunx run eslint --fix

uv-format: ## Use uv to format the Berg-Agents package code
	@echo "Formatting the Berg-Agents package code with uv"
	@.venv/bin/uv check --fix

uv-install: ## Install uv dependencies for the Berg-Agents package
	@echo "Installing Berg-Agents package and uv dependencies"
	@.venv/bin/uv pip install -e .


uv-lock: uv-install ## Use uv to lock the dependencies and generate a requirements.txt file for the Berg-Agents package
	@echo "Locking the dependencies with uv and generating requirements.txt for Berg-Agents package"
	@.venv/bin/uv lock
	@.venv/bin/uv export --format requirements.txt --output-file requirements.txt -q

uv-build: uv-lock ## Use uv to build the Berg-Agents package
	@echo "Build the Berg-Agents package with uv"
	@.venv/bin/uv build


# ======= Plugin System targets =======
run-build-plugin-system: ## Run the makefile for the plugin_system package
	@echo "Running the makefile for the plugin_system package"
	@make -C plugin_system uv-build-plugin-system

# ======= Shared-ToDo plugin targets =======
run-make-shared-todo-plugin: run-build-plugin-system ## Install uv dependencies for the plugin
	@echo "Running make file for the Shared-ToDo plugin package"
	@make -C berg_plugins/shared-todo build-ui-shared-todo-plugin
	@make -C berg_plugins/shared-todo uv-build-shared-todo-plugin

# ======= General targets =======
run-all-build: ## Run all bun and uv build commands for the Berg-Agents package and the Shared-ToDo plugin
	@echo "Running all build commands for the Berg-Agents package and the Shared-ToDo plugin"
	@make build-ui
	@make run-build-plugin-system
	@make run-make-shared-todo-plugin
	@make uv-build


make-install-and-run: ## Run bash script install_and_run.sh to build and start Berg-Agents web-ui
	@echo "Running install_and_run.sh script to build and start Berg-Agents web-ui"
	@bash install_and_run.sh

run-berg-agents-web: ## Start the WHOLE app: PostgreSQL + Python backend + Next UI, one browser URL
	@echo "Starting Berg-Agents: postgres :$(BERG_PG_PORT), backend :$(BERG_BACKEND_PORT), UI :$(BERG_UI_PORT)"
	@echo "Open http://localhost:$(BERG_UI_PORT) in your browser."
	@# Preflight: a busy port is the one failure that arrives as a bare
	@# EADDRINUSE from Next or Uvicorn, naming neither the port nor the process
	@# holding it, after everything else has already started. Checking first
	@# turns that crash into a sentence that says who to talk to.
	@busy=0; for port in $(BERG_BACKEND_PORT) $(BERG_UI_PORT); do \
		if ss -ltn 2>/dev/null | grep -q ":$$port "; then \
			echo "Port $$port is already in use — Berg-Agents is probably already running:"; \
			ss -ltnp 2>/dev/null | grep ":$$port " | sed 's/^/    /'; \
			echo "    Open http://localhost:$(BERG_UI_PORT), or stop the old one with 'make stop-berg-agents'."; \
			busy=1; \
		fi; \
	done; \
	if [ "$$busy" = "1" ]; then exit 1; fi
	@# postgres FIRST: the orchestrator's world reads and writes it, and without
	@# it every orchestration run enqueues into a queue nothing drains — the turn
	@# appears to start and then goes permanently silent.
	@$(MAKE) postgres-start
	@BERG_BACKEND_URL=$(BERG_BACKEND_URL) WORKFLOW_TARGET_WORLD="@workflow/world-postgres" \
		WORKFLOW_POSTGRES_URL="postgres://world:world@localhost:$(BERG_PG_PORT)/world" \
		$(MAKE) -j 2 run-backend run-ui

# The two halves, run in parallel by the target above. Kept as separate targets
# so either can be started alone when debugging one side.
run-backend: ## Start only the Python backend (API, sessions, specialists)
	@echo "Starting the Berg-Agents backend on port $(BERG_BACKEND_PORT)"
	@.venv/bin/uv run berg_agents --web --hot-reload --debug --log-level=info --port $(BERG_BACKEND_PORT)

run-ui: ## Start only the Next UI (expects the backend already running)
	@echo "Starting the Berg-Agents UI on port $(BERG_UI_PORT)"
	@# The proxy destination lives in the build, not the environment, so a build
	@# baked for another port must be rebuilt rather than served. Production
	@# only: `next dev` (run-ui-dev) re-reads the config per request and needs no
	@# such check — which is why the dev targets are left alone here.
	@if [ -f "$(UI_BUILD_PORT_FILE)" ]; then \
		baked=$$(cat "$(UI_BUILD_PORT_FILE)"); \
		if [ "$$baked" != "$(BERG_BACKEND_PORT)" ]; then \
			echo "This UI build proxies to :$$baked but the backend is on :$(BERG_BACKEND_PORT) — rebuilding."; \
			$(MAKE) BERG_BACKEND_PORT=$(BERG_BACKEND_PORT) build-ui; \
		fi; \
	else \
		echo "No UI build record at $(UI_BUILD_PORT_FILE) — building once so the proxy target is known."; \
		$(MAKE) BERG_BACKEND_PORT=$(BERG_BACKEND_PORT) build-ui; \
	fi
	@bun --cwd berg_agents/ui/webapp next start -p $(BERG_UI_PORT)

run-ui-dev: ## Start only the Next UI in dev mode (hot reload)
	@echo "Starting the Berg-Agents UI (dev) on port $(BERG_UI_PORT)"
	@BERG_BACKEND_URL=$(BERG_BACKEND_URL) bun --cwd berg_agents/ui/webapp next dev -p $(BERG_UI_PORT)

make-social-cheatsheet-app-dev: ## Add social-cheatsheet-app as root-dir to run berg-agents in that project
	@BERG_AGENT_ROOT_DIR=/home/sofiabillberg/code-projects/social-cheatsheet-app/
	@.venv/bin/uv run berg_agents --web --hot-reload  --debug --log-level=info --port 8007

run-social-cheatsheet-app-dev: ## Start dev environment with custom backend target
	@echo "Starting Berg Agents Development Environment, open http://localhost:3000 in your browser to access the dev web-ui"
	@BERG_AGENT_ROOT_DIR=/home/sofiabillberg/code-projects/social-cheatsheet-app/
	$(MAKE) -j 2 run-frontend-dev make-social-cheatsheet-app-dev

run-backend-dev: ## Start the Python backend on a different port (8007) for side-by-side dev
	@echo "Running the Berg-Agents backend on port 8007"
	@.venv/bin/uv run berg_agents --web --hot-reload  --debug --log-level=info --port 8007

run-frontend-dev: ## Start the Next UI in dev mode, proxying to the :8007 backend
	@echo "Starting Berg Agents UI dev server on port $(BERG_UI_PORT), backend on :8007"
	@BERG_BACKEND_URL=http://127.0.0.1:8007 bun --cwd berg_agents/ui/webapp next dev -p $(BERG_UI_PORT)

run-berg-agents-dev: postgres-start ## Dev environment: Python backend + Next dev server, hot reload on both
	@echo "Starting Berg Agents Dev Environment — open http://localhost:$(BERG_UI_PORT)"
	@# postgres-start FIRST, as in run-berg-agents-web: the Next server loads the
	@# workflow world's instrumentation hook at boot, and without berg's database
	@# on :5434 the dev server exits with code 1 right after printing "Ready".
	@# Dev reads its config per request rather than baking it into a build, so the
	@# backend port comes from the environment here and no build record is
	@# involved — which is why this target needs no stale-build check.
	@BERG_BACKEND_URL=http://127.0.0.1:8007 $(MAKE) -j 2 run-frontend-dev run-backend-dev
stop-berg-agents: ## Find process that might be related to the Berg-Agents web-ui, list then and let the user chose
					# which ones to stop, if any
	# Search for any ports that the Berg-Agents web-ui might be running on
	# - filter out non-listning processes and if thet are not a uv/python process,
	# list processes, and ask for confirmation before stopping - ensure user can see what processes are running
	# and confirm before stopping them and chose individual processes
	@echo "Found the following possible Berg-Agents web-ui processes:"
	@lsof -i :8000-9000 | grep LISTEN
	# Ask which processes to stop, if any - let the user choose by process id, and confirm before stopping
	@read -p "Enter the process ID(s) to stop (separated by spaces), or press Enter to skip: " pids; \
	if [ -n "$$pids" ]; then \
		for pid in $$pids; do \
			if ps -p $$pid > /dev/null; then \
				read -p "Are you sure you want to stop process $$pid? (y/n) " confirm; \
				if [ "$$confirm" = "y" ]; then \
					kill -9 $$pid; \
					echo "Stopped process $$pid"; \
				else \
					echo "Skipped stopping process $$pid"; \
				fi; \
			else \
				echo "Process $$pid not found"; \
			fi; \
		done; \
	else \
		echo "No processes selected to stop"; \
	fi

# ======= Formatters and documentation targets =======

run-diagrams: ## Run the bash script to generate diagrams for the Berg-Agents package
	@echo "Running the bash script to generate diagrams for the Berg-Agents package"
	@bash project_utils/run_diagrams.sh

run-formatters: ## Run the bash script to run formatters for the Berg-Agents package
	@echo "Running the bash script to run formatters for the Berg-Agents package"
	@bash project_utils/run_formatters.sh

run-apidocs: ## Run the bash script to generate API docs for the Berg-Agents package
	@echo "Running the bash script to generate API docs for the Berg-Agents package"
	@bash project_utils/run_apidocs.sh

render-readme: ## Run the bash script to render the README.md file for the Berg-Agents package
	@echo "Running the bash script to render the README.md file for the Berg-Agents package"
	@bash project_utils/render_readme.sh

panasch-lint: ## Ru n panache formatter
	@panache lint . --config .panache.toml --fix

panache-format: ## Run panache formatter
	@panache format .  berg_plugins berg_agents docs  --config .panache.toml

.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; \
		{printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
