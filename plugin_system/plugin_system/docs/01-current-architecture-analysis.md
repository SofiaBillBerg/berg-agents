# Current Berg Agents Architecture Analysis

*Generated: 2026-10-10*

## Overview

Berg Agents is a sophisticated multi-agent system built on Pydantic AI with a modular, extensible architecture.
The system follows a harness-based execution model with multiple specialized agents working together.

## Core Components

### 1. **Harness System** (`../../../berg_agents/core/harness`)

The orchestration layer that coordinates agent execution:
- **Guardian** - Entry point, safety checks, and risk assessment
- **Planner** - Task decomposition and step planning
- **Implementation** - Executes plans with workspace tools
- **Curator** - Reviews and validates results
- **Learning Gate** - Captures outcomes for continuous improvement

### 2. **Agents** (`../../../berg_agents/agents`)

Specialized agent implementations:
- `guardian.py` - Security and safety validation
- `planner.py` - Task planning and decomposition
- `implementation.py` - Code execution and file operations
- `curator.py` - Quality review and validation
- `learning.py` - Learning from outcomes
- `chat_agent.py` - Interactive chat interface
- `workspace_toolset.py` - File system operations

### 3. **Capabilities System** (`../../../berg_agents/capabilities`)

Current capability types:

#### **Skills** (`skills.py`)

- Reads `SKILL.md` files (Anthropic Agent Skills format)
- YAML frontmatter (name, description) + Markdown body
- **Deferred loading** - catalog entry shown, full content loaded on demand
- Path resolution: workspace → repo root → CWD
- Single file, directory, or directory of skills
- Hard cap: 6000 chars per skill body

#### **MCP Toolsets** (`mcp_toolsets.py`)

- Reads `../../../.berg-agents` (Claude-style `mcpServers` format)
- Remote (HTTP) and local (stdio) transports
- Automatic `mcp_<server>__<tool>` naming
- Sensitive servers require human approval
- **Resilient design** - dead servers degrade gracefully
- Process-wide caching with keep-alive

#### **Web Backends** (`web_backends.py`)

- Search and fetch capabilities
- Plugin-based architecture already present

#### **Base** (`base.py`)

- Risk classification vocabulary: `low`, `medium`, `high`
- Used by tools and harness routing for HITL decisions

#### **Registry** (`registry.py`)

- Tool catalog and routing
- Maps task types to required tools
- Single source of truth for tool requirements

### 4. **Provider System** (`../../../berg_agents/providers`)

Config-driven model registry:

- **No hardcoded providers** - all from `../../../.berg-agents`
- Pure constructor pattern: options map 1:1 to kwargs
- Environment variable expansion: `{env:VAR}`
- Per-model option overrides
- Model tiers for complexity routing

```json
{
  "providers": {
    "ollama": {
      "name": "ollama(Local)",
      "options": {"baseURL": "{env:OLLAMA_BASE_URL}"},
      "models": {"qwen3.5:9b": {}, "mistral:latest": {}}
    }
  }
}
```

### 5. **Configuration** (`../../../berg_agents/config`)

- `bergagents.jsonc` - main config
- `mcp.json` - MCP server definitions
- Environment variable support
- Settings validation with Pydantic

### 6. **Tools** (`../../../berg_agents/tools`)

Currently minimal - mostly I/O utilities

### 7. **UI Layer** (`../../../berg_agents/ui`)

- FastAPI web server
- Rich terminal UI
- Session management

## Key Architectural Patterns

### 1. **Deferred Loading**

Skills use a catalog-then-load pattern:
- Models see only `id` + `description` (~20 lines for 20 skills)
- Full content loaded via `load_capability` tool when needed
- Prevents context window flooding

### 2. **Resilient External Resources**

MCP toolsets wrap external processes:
- Listing failures → empty tool list
- Call failures → error message, not exception
- One broken server doesn't break the turn

### 3. **Risk-Based HITL**

Tools declare risk levels:
- `low` - auto-execute
- `medium` - context-dependent
- `high` - requires approval

### 4. **Config-Driven Extensibility**

- Providers defined in JSON, not code
- Skills from file paths
- MCP servers from config
- No recompilation needed

### 5. **Single Source of Truth**

- Provider registry: model resolution
- Tool catalog: routing rules
- Risk vocabulary: HITL decisions

## Extension Points

Current system already has several extension mechanisms:

1. **Skills** - Drop `SKILL.md` files in configured paths
2. **MCP Servers** - Add to `../../../.berg-agents`
3. **Providers** - Add to `../../../.berg-agents`
4. **Web Backends** - Already uses plugin architecture
5. **Tools** - Register in tool catalog

## Gaps for a Full Plugin System

What's missing for a unified plugin system:

1. **No unified plugin interface** - skills, MCP, web backends use different patterns
2. **No dependency resolution** - plugins can't declare dependencies on each other
3. **No version management** - no versioning or compatibility checking
4. **No lifecycle hooks** - can't run code on load/enable/disable/unload
5. **No inter-plugin communication** - no event bus or message passing
6. **Limited metadata** - no author, license, homepage, etc.
7. **No isolation** - plugins run in the same process space
8. **No discovery service** - must manually configure paths/servers
9. **Manual configuration** - no UI for enabling/disabling plugins
10. **No plugin API contracts** - plugins directly access internals

## Strengths to Preserve

1. **Deferred loading** - critical for context efficiency
2. **Resilient failures** - graceful degradation
3. **Config-driven** - no code changes to extend
4. **Risk-based security** - HITL for sensitive operations
5. **MCP compatibility** - standard protocol support

## Recommended Approach

Build a **unified plugin layer** that:
- Wraps existing capabilities (skills, MCP, web backends)
- Adds missing lifecycle, dependencies, versioning
- Preserves deferred loading and resilience patterns
- Maintains backward compatibility
- Uses Pydantic for validation

Next steps: Define plugin interface and manifest schema.
