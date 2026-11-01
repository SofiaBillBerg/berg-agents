# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
SHELL := $(SHELL)
.SHELLFLAGS := -c

# Makefile for the project, providing targets for installing dependencies and building the Shared ToDo plugin package for Berg-Agents thourgh bun and uv.

# .PHONY: bun-install-plugin build-ui-plugin eslint-fix-plugin uv-format-plugin uv-install-plugin uv-build-plugin uv-lock-plugin
# .default-goal := help




bun-install-shared-todo-plugin: ## Install bun dependencies for shared-todo plugin app
	@echo "Installing bun dependencies for shared-todo plugin app"
	@bun install

build-ui-shared-todo-plugin: bun-install-shared-todo-plugin ## Use bun to build the UI for the shared-todo plugin app
	@echo "Building UI for the shared-todo plugin app"
	@bun run build:ui

tsc-lint-shared-todo-plugin: ## Use bun to lint the UI for the shared-todo plugin app
	@echo "Linting UI for the shared-todo plugin app"
	@bun run tsc --noEmit --skipLibCheck

#eslint-fix-plugin: ## Use bun to fix eslint issues in the UI
#	@echo "Fixing eslint issues in the UI"
#	@bunx eslint --fix

uv-format-shared-todo-plugin: ## Use uv to format the shared-todo plugin app
	@echo "Formatting the shared-todo plugin app with uv"
	@.venv/bin/uv check --fix

uv-install-shared-todo-plugin: ## Install uv dependencies for the shared-todo plugin app
	@echo "Installing the shared-todo plugin app and uv dependencies"
	@uv pip install -e .


uv-build-shared-todo-plugin: uv-install-shared-todo-plugin ## Use uv to build the shared-todo plugin app
	@echo "Building the shared-todo plugin app with uv"
	@.venv/bin/uv build

uv-lock-shared-todo-plugin: ## Use uv to lock the dependencies and generate a requirements.txt file
	@echo "Locking the shared todo app's dependencies with uv and generating requirements.txt"
	@.venv/bin/uv lock
	@.venv/bin/uv export --format requirements.txt --output-file requirements.txt -q


.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
