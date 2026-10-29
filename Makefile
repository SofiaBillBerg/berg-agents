SHELL := $(SHELL)
.SHELLFLAGS := -c

# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html

# Makefile for the project, providing targets for installing dependencies and building the UI and uv plugin.

bun-install: ## Install bun dependencies for Berg-Agents UI
	@echo "Installing bun dependencies"
	@bun install --cwd berg_agents/ui/webapp/

build-ui: bun-install ## Use bun to build the frontend for Berg-Agents UI
	@echo "Building Berg-Agents UI"
	@bun --cwd berg_agents/ui/webapp next build


tsc-lint:  ## Use bun to lint the Berg-Agents UI
	@echo "Linting Berg-Agents UI"
	@bunx tsc  -p ./berg_agents/ui/webapp/ --noEmit --skipLibCheck
#
#eslint-fix: ## Use bun to fix eslint issues in the Berg-Agents UI
#	@echo "Fixing eslint issues in the Berg-Agents UI"
#	@cd berg_agents/ui/webapp && bunx run eslint --fix

uv-format: ## Use uv to format the Berg-Agents package code
	@echo "Formatting the Berg-Agents package code with uv"
	@uv check --fix

uv-install: ## Install uv dependencies for the Berg-Agents package
	@echo "Installing Berg-Agents package and uv dependencies"
	@uv pip install -e .


uv-build: uv-install ## Use uv to build the Berg-Agents package
	@echo "Build the Berg-Agents package with uv"
	@uv build

uv-lock: uv-build ## Use uv to lock the dependencies and generate a requirements.txt file for the Berg-Agents package
	@echo "Locking the dependencies with uv and generating requirements.txt for Berg-Agents package"
	@uv lock
	@uv export --format requirements.txt --output-file requirements.txt -q

run-make-plugin: ## Install uv dependencies for the plugin
	@echo "Running make file for the Shared-ToDo plugin package"
	@make -C berg_plugins/shared-todo build-ui-plugin
	@make -C berg_plugins/shared-todo uv-build-plugin

run-all-build: ## Run all bun and uv build commands for the Berg-Agents package and the Shared-ToDo plugin
	@echo "Running all build commands for the Berg-Agents package and the Shared-ToDo plugin"
	@make build-ui
	@make run-make-plugin
	@make uv-build



.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
