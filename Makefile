SHELL := $(SHELL)
.SHELLFLAGS := -c

# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html

# Makefile for Berg-Agents project, providing targets for installing dependencies and building
# the berg-agents package through bun and uv.

# ======= Berg-Agents package targets =======
bun-install: ## Install bun dependencies for Berg-Agents UI
	@echo "Installing bun dependencies"
	@bun install --cwd berg_agents/ui/webapp/

build-ui: bun-install ## Use bun to build the frontend for Berg-Agents UI
	@echo "Building Berg-Agents UI"
	@bun --cwd berg_agents/ui/webapp next build


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

uv-lock: uv-install ## Use uv to lock the dependencies and generate a requirements.txt file for the Berg-Agents package
	@echo "Locking the dependencies with uv and generating requirements.txt for Berg-Agents package"
	@.venv/bin/uv lock
	@.venv/bin/uv export --format requirements.txt --output-file requirements.txt -q

uv-install: ## Install uv dependencies for the Berg-Agents package
	@echo "Installing Berg-Agents package and uv dependencies"
	@.venv/bin/uv pip install -e .


uv-build: uv-install ## Use uv to build the Berg-Agents package
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

run-berg-agents-web: ## Quickstart berg-agents webui on port 8001
	@echo "Running the Berg-Agents web-ui on port 8001"
	@.venv/bin/uv run berg_agents --web --hot-reload --port 8001


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
