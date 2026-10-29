# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
SHELL := $(SHELL)
.SHELLFLAGS := -c

# Makefile for the project, providing targets for installing dependencies and building the Shared ToDo plugin package for Berg-Agents thourgh bun and uv.

# .PHONY: bun-install-plugin build-ui-plugin eslint-fix-plugin uv-format-plugin uv-install-plugin uv-build-plugin uv-lock-plugin
# .default-goal := help


bun-install-plugin: ## Install bun dependencies plugin app
	@echo "Installing bun dependencies"
	@bun install

build-ui-plugin: bun-install-plugin ## Use bun to build the UI
	@echo "Building UI"
	@bun run build:ui

tsc-lint-plugin: ## Use bun to lint the UI
	@echo "Linting UI"
	@bun run tsc --noEmit --skipLibCheck

#eslint-fix-plugin: ## Use bun to fix eslint issues in the UI
#	@echo "Fixing eslint issues in the UI"
#	@bunx eslint --fix

uv-format-plugin: ## Use uv to format the plugin code
	@echo "Formatting the plugin code with uv"
	@.venv/bin/uv check --fix

uv-install-plugin: ## Install uv dependencies for the plugin
	@echo "Installing the project package and uv dependencies"
	@uv pip install -e .


uv-build-plugin: uv-install-plugin ## Use uv to build the plugin
	@echo "Build the package with uv"
	@.venv/bin/uv build

uv-lock-plugin: ## Use uv to lock the dependencies and generate a requirements.txt file
	@echo "Locking the dependencies with uv and generating requirements.txt"
	@.venv/bin/uv lock
	@.venv/bin/uv export --format requirements.txt --output-file requirements.txt -q


.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
