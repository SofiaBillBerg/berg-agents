SHELL := $(SHELL)
.SHELLFLAGS := -c
# Self-Documented Makefile see https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html


# ======= Berg-Agents package targets =======
bun-install: ## Install bun dependencies for Berg-Agents UI
	@echo "Installing bun dependencies"
	@bun install

build-ui: bun-install ## Use bun to build the frontend for Berg-Agents UI
	@echo "Building Berg-Agents UI"
	@bun next build


tsc-lint:  ## Use bun to lint the Berg-Agents UI
	@echo "Linting Berg-Agents UI"
	@bunx tsc # --noEmit --skipLibCheck
#
eslint-fix: ## Use bun to fix eslint issues in the Berg-Agents UI
	@echo "Fixing eslint issues in the Berg-Agents UI"
	#@cd berg_agents/ui/webapp &&
	@bunx eslint --fix


.PHONY: help

help:
	@echo "Displaying available targets"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; \
		{printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
