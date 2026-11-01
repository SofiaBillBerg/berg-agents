# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
SHELL := $(SHELL)
.SHELLFLAGS := -c

# Makefile for the project, providing targets for installing dependencies and building the Shared ToDo plugin package for Berg-Agents thourgh bun and uv.

# .PHONY: bun-install-plugin build-ui-plugin eslint-fix-plugin uv-format-plugin uv-install-plugin uv-build-plugin uv-lock-plugin
# .default-goal := help


#bun-install-plugin: ## Install bun dependencies plugin app
#	@echo "Installing bun dependencies"
#	@bun install
#
#build-ui-plugin: bun-install-plugin ## Use bun to build the UI
#	@echo "Building UI"
#	@bun run build:ui
#
#tsc-lint-plugin: ## Use bun to lint the UI
#	@echo "Linting UI"
#	@bun run tsc --noEmit --skipLibCheck

#eslint-fix-plugin: ## Use bun to fix eslint issues in the UI
#	@echo "Fixing eslint issues in the UI"
#	@bunx eslint --fix

uv-format-plugin-system: ## Use uv to format the plugin-system package code
	@echo "Formatting the plugin code with uv"
	@uv check --fix

uv-lock-plugin-system: uv-install-plugin-system ## Use uv to lock the dependencies and generate a requirements.txt file
	@echo "Locking the dependencies with uv and generating requirements.txt"
	@uv lock
	@uv export --format requirements.txt --output-file requirements.txt -q


uv-install-plugin-system: ## Install uv dependencies for the plugin-system package
	@echo "Installing the project package and uv dependencies"
	@uv pip install -e .


uv-build-plugin-system: uv-install-plugin-system ## Use uv to build the plugin-system package
	@echo "Build the package with uv"
	@uv build


.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
