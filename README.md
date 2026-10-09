<!-- README.md is generated from README.qmd. Please edit that file -->

\`\`\`{r} #\| include: false

knitr::opts_chunk$set( collapse = TRUE, comment = “#\>” )

    # berg_agents

    <!-- badges: start -->

    > BergAgents - a local, LLM-driven code assistant with a framework-agnostic core and provider-centric configuration.

    <!-- badges: end -->

    ![Berg-Agents Overview](docs/visualizations/png/packages_berg_agents.png "Berg Agents overview")

    ## Quick Start

    ```bash
    # Install dependencies (uv is recommended)
    uv venv .venv
    source .venv/bin/activate
    uv pip install -e .

    # Interactive terminal UI
    python -m berg_agents --tui

    # Web UI (default: http://127.0.0.1:8001)
    python -m berg_agents --web

## What it is

A task engine (**Harness**) drives specialized subagents - Guardian,
Planner, Implementation, Curator, Learning - against any
OpenAI-compatible provider:

- **Harness engine**: guardian → planner → implementation → curator,
  with a learning gate that records task → model → outcome and adapts
  routing
- **Human-AI balance**: Guardian decides when to ask (risk × complexity
  × confidence); mutating tools pause for approve / reject / edit
- **Provider-centric config**: each model belongs to a provider;
  baseURL/apiKey resolve FROM the model id - never from a global flag
- **MCP integration**: external MCP servers (stdio or HTTP); tools
  prefixed `mcp_<server>__<tool>`
- **TUI + web, same surface**: interactive terminal
  (`berg_agents/ui/cli_ui.py`) and Next.js + FastAPI web UI list
  identical slash commands (`/harness`, `/task`, …) and stream the same
  Harness task lifecycle

See [docs/USAGE.qmd] for TUI, Python API, and web examples.

## Tutorials

The following short tutorials walk through common use-cases:

1.  **Simple code-review agent**

    ``` bash
    # Create a guardian-only task to review a Python file
    python -m berg_agents --task "Review src/utils.py for PEP-8 violations"
    ```

    The response is streamed back in the terminal and stored in the
    learning gate.

2.  **Building a multi-step workflow**

    ``` bash
    # Plan → Implement → Curate workflow
    python -m berg_agents --task "Refactor the authentication module" \
        --plan "Identify security gaps" \
        --implement "Add rate limiting" \
        --curate "Write unit tests"
    ```

    The harness automatically routes each step to the appropriate
    subagent.

3.  **Using MCP tools**

    ``` jsonc
    // config/mcp.json
    {
      "github__search": {
        "type": "stdio",
        "command": "gh"
      }
    }
    ```

    Then call the tool from the UI or CLI:

    ``` bash
    python -m berg_agents --task "Search for repos about 'BergAgents' on GitHub"
    ```

4.  **Customizing the Harness via `bergagents.jsonc`**

    ``` jsonc
    {
      "providers": {
        "openai": {
          "baseURL": "https://api.openai.com",
          "apiKey": "${env:OPENAI_API_KEY}"
        }
      },
      "harness": {
        "enable_learning": true,
        "enable_inference": true
      },
      "model_routing": {
        "gpt-4o": { "provider": "openai", "complexity": 2 },
        "claude-3-sonnet": { "provider": "anthropic", "complexity": 1 }
      }
    }
    ```

    This file lives in `config/bergagents.jsonc` and is automatically
    merged with environment overrides.

## Configuration

``` bash
config/bergagents.jsonc   # providers, harness, model_routing, hitl_rules, plugins, agents
.env                      # secrets referenced as `${env:VAR_NAME}`
```

| Layer | Source |
|----------------------------------|--------------------------------------|
| Config file | `config/bergagents.jsonc` - `providers` block + `harness`/`model_routing`/`hitl_rules` |
| Secrets | `.env` file, referenced with `${env:VAR_NAME}` |
| Overrides | `BERG_AGENT_*` environment variables |
| External tools | `config/mcp.json` for MCP server configuration |

See [docs/CONFIGURATION.qmd] for the full reference.

<figure>
<img src="docs/visualizations/png/packages_berg_agents.png"
title="Berg Agents Config Modules" alt="Berg-Agents Config" />
<figcaption aria-hidden="true">Berg-Agents Config</figcaption>
</figure>

## Documentation

| Page | Description |
|-----------------------|-------------------------------------------------|
| [QUICKSTART] | Installation and first run |
| [USAGE][docs/USAGE.qmd] | TUI, Python API, and web workflows |
| [API] | Module map for the codebase |
| [TOOLS] | Built-in tools, capabilities, and MCP |
| [CONFIGURATION][docs/CONFIGURATION.qmd] | Provider-centric config, `.env`, and env vars |
| [CONTRIBUTING] | Guidelines for contributing |
| [FAQ] | Common questions and troubleshooting |
| **TUTORIALS** (this page) | Step-by-step examples for common tasks |

## Getting Help

- Read the [QUICKSTART guide][QUICKSTART] for installation
- Check [USAGE examples][docs/USAGE.qmd] for common workflows
- See [TOOLS documentation][TOOLS] to understand agent capabilities
- Review [FAQ] for troubleshooting tips
- API reference is in [API]
- Explore the [TUTORIALS] section above for ready-to-run snippets

## Contributing

Please read our [CONTRIBUTING] guide for details on coding standards,
testing, and the submission process.

## License

**Version**: 0.2.0 \| **License**: MIT

  [docs/USAGE.qmd]: docs/USAGE.qmd
  [docs/CONFIGURATION.qmd]: docs/CONFIGURATION.qmd
  [QUICKSTART]: docs/QUICKSTART.qmd
  [API]: docs/API.qmd
  [TOOLS]: docs/TOOLS.qmd
  [CONTRIBUTING]: docs/CONTRIBUTING.qmd
  [FAQ]: docs/FAQ.qmd
  [TUTORIALS]: #tutorials
