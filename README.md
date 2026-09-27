# Berg Agents
Sofia Billger Bergström

<!-- README.md is generated from README.qmd. Please edit that file -->


<!-- badges: start -->

> BergAgents — a local, LLM-driven code assistant with a
> framework-agnostic core and provider-centric configuration.

<!-- badges: end -->

## Quick Start

``` bash
# Install dependencies (uv is recommended)
uv venv .venv
source .venv/bin/activate
uv pip install -e .

# Interactive terminal UI
python -m berg_agents --tui

# Web UI (default: http://127.0.0.1:8001)
python -m berg_agents --web
```

## What it is

A task engine (**Harness**) drives specialized subagents — Guardian,
Planner, Implementation, Curator, Learning — against any
OpenAI-compatible provider:

- **Harness engine**: guardian → planner → implementation → curator,
  with a learning gate that records task → model → outcome and adapts
  routing
- **Human-AI balance**: Guardian decides when to ask (risk × complexity
  × confidence); mutating tools pause for approve / reject / edit
- **Provider-centric config**: each model belongs to a provider;
  baseURL/apiKey resolve FROM the model id — never from a global flag
- **MCP integration**: external MCP servers (stdio or HTTP); tools
  prefixed `mcp_<server>__<tool>`
- **TUI + web, same surface**: interactive terminal
  (`berg_agents/ui/cli_ui.py`) and Next.js + FastAPI web UI list
  identical slash commands (`/harness`, `/task`, …) and stream the same
  Harness task lifecycle

See [docs/USAGE.qmd](./docs/USAGE.qmd) for TUI, Python API, and web
examples.

## Configuration

``` bash
config/bergagents.jsonc   # providers, harness, model_routing, hitl_rules, plugins, agents
.env                      # secrets referenced as ${env:VAR_NAME}
```

| Layer | Source |
|----|----|
| Config file | `config/bergagents.jsonc` — `providers` block + `harness`/`model_routing`/`hitl_rules` |
| Secrets | `.env` file, referenced with `${env:VAR_NAME}` |
| Overrides | `BERG_AGENT_*` environment variables |
| External tools | `mcp.json` for MCP server configuration |

See [docs/CONFIGURATION.qmd](docs/CONFIGURATION.qmd) for the full
reference.

## Documentation

| Page | Description |
|----|----|
| [QUICKSTART](docs/QUICKSTART.qmd) | Installation and first run |
| [USAGE](docs/USAGE.qmd) | TUI, Python API, and web workflows |
| [API](docs/API.qmd) | Module map for the codebase |
| [TOOLS](docs/TOOLS.qmd) | Built-in tools, capabilities, and MCP |
| [CONFIGURATION](docs/CONFIGURATION.qmd) | Provider-centric config, `.env`, and env vars |
| [CONTRIBUTING](docs/CONTRIBUTING.qmd) | Guidelines for contributing |
| [FAQ](docs/FAQ.qmd) | Common questions and troubleshooting |

## Getting Help

- Read the [QUICKSTART guide](docs/QUICKSTART.qmd) for installation
- Check [USAGE examples](docs/USAGE.qmd) for common workflows
- See [TOOLS documentation](docs/TOOLS.qmd) to understand agent
  capabilities
- Review [FAQ](docs/FAQ.qmd) for troubleshooting tips

------------------------------------------------------------------------

**Version**: 0.2.0 \| **License**: MIT
