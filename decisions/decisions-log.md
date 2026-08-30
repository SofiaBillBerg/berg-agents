<!-- Context: decisions-log | Priority: medium | Version: 1.2 | Updated: 2026-08-13 -->

# Decisions Log

**Purpose**: Canonical project decisions live here. This file is mirrored in
`.opencode/context/project-intelligence/decisions-log.md` for project-intelligence routing; keep both files in sync when
updating decisions.

**Last Updated**: 2026-08-28

## Quick Reference

**Update Triggers**: Architecture changes | Technology decisions | Design choices | Verification/process learnings
**Audience**: Developers, architects, AI agents **Source of truth**: Git history, project documentation, AGENTS.md

## Decision Index

| Date       | Decision                                                                    | Rationale                                                                                                                                                                      | Impact                                                               |
|------------|-----------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------|
| 2026-08-11 | Use LangChain + LangGraph + DeepAgents                                      | Established agent framework with graph capabilities                                                                                                                            | Foundation for agent architecture                                    |
| 2026-08-28 | Move AWAY from LangGraph as core — Orchestrator is the spine                | LangGraph-coupled server violated framework-agnostic principle. New Orchestrator is core; LangGraph is optional adapter.                                                       | Core no longer imports LangChain. Backends are optional.             |
| 2026-08-28 | Web UI talks to Orchestrator, not LangGraph                                 | Prevent drift. React app uses `/api/orchestrator` endpoints. LangGraph streaming kept as legacy mode only.                                                                      | FastAPI routes added for orchestrator. App.jsx has mode toggle.      |
| 2026-08-28 | BergAgentsPlan.md is north star                                              | Prevent future drifting. All implementation must align with this document. If plan changes, update doc FIRST.                                                                  | Single source of truth for architecture.                             |
| 2026-08-28 | Slash commands for TUI + WebUI                                               | Predefined commands (agents/models/stats/tools/...) should be slash commands inside interactive UI, not top-level CLI. Single-shot `berg-agents new-file` is not BergAgents.   | 17 slash commands in `cli.py` + `SlashCommandPicker` + `App.jsx`/`useOrchestrator.js`. TUI/WebUI only. |
| 2026-08-28 | NativeAdapter makes LangGraph truly optional                                 | App must run without LangChain installed. NativeAdapter uses stdlib urllib (zero deps) for OpenAI-compatible APIs.                                                            | `backends/native_adapter.py` + `NativeAgent` (AbstractAgent). 149 tests. |
| 2026-08-28 | Config: orchestrator/model_routing/hitl_rules/plugins/agents in bergagents.jsonc | Config must reflect multi-agent reality. Keep `providers` as source of truth; `model_routing`/`hitl_rules` drive Orchestrator/Guardian; `profiles.yaml` is LangGraph-only.   | Extended `bergagents.jsonc` + `Settings` + `BergAgentsApp.create()` wiring. Backwards-compatible. |
| 2026-08-28 | BergAgentsApp as main entry point                                            | Need a single place to wire Orchestrator + ModelRouter + LearningGate + plugins. Export from `berg_agents/__init__.py`.                                                       | `berg_agents/app.py` + `get_app()` singleton. CLI/Web/API all use it. |
| 2026-08-11 | Provider-agnostic approach                                                  | Flexibility across LLM providers                                                                                                                                               | Reduced vendor lock-in                                               |
| 2026-08-11 | Human-in-the-loop middleware                                                | Better control and oversight                                                                                                                                                   | Enhanced user experience                                             |
| 2026-08-11 | Persistent state management                                                 | Session continuity                                                                                                                                                             | Improved user experience                                             |
| 2026-08-11 | Tool-based architecture                                                     | Reusable capabilities                                                                                                                                                          | Modular design                                                       |
| 2026-08-12 | Close duplicate plans before claiming completion                            | Prevents stale active plans after compaction boundaries                                                                                                                        | Accurate project state                                               |
| 2026-08-12 | Trust project-venv verification over LSP/static warnings when they conflict | Static analysis can be misconfigured; runtime/pyrefly results reflect actual state                                                                                             | Faster debugging, fewer false alarms                                 |
| 2026-08-13 | MCP tool prefixing                                                          | All 43 MCP tools use `mcp_<server>__<tool>` naming format (github: 26, memory: 9, context7: 2, codegraph: 1, docs-langchain: 3, reference-langchain: 2)                        | Consistent tool naming enables HITL gating and env var expansion     |
| 2026-08-13 | Human-in-the-loop gating                                                    | Sensitive servers (github, memory) intercepted via HumanInTheLoopMiddleware; read-only servers (context7, docs-langchain, reference-langchain) functional without interruption | Enhanced security and user control per policy                        |
| 2026-08-13 | Environment variable expansion                                              | ${VAR} placeholders in .mcp.json resolved from gitignored .env file at config load; verified expand_env_vars() functional                                                      | Secrets never hardcoded; gitignored .env file used for actual values |
| 2026-08-13 | .mcp.json hardening                                                         | ${GITHUB_PERSONAL_ACCESS_TOKEN} and ${CONTEXT7_API_KEY} placeholders (not hardcoded); actual secrets in gitignored .env                                                        | Security best practice; .mcp.json version-controlled safely          |
| 2026-08-13 | DEFAULT_SYSTEM_PROMPT MCP guardrail                                         | Section added documenting MCP security policy: github/memory interception, HITL approval flow, read-only server exception                                                      | Policy enforcement in agent system prompt                            |

## Current Architecture Decisions

### 1. Technology Stack Selection

**Decision**: Python >=3.11 with uv for dependency management

**Context**: Modern Python ecosystem with strong typing support

**Implications**:

- Full type annotations required
- Modern Python features available
- Easy dependency management

**Alternatives Considered**:

- Node.js/TypeScript: Rich ecosystem but less typing
- Java: Strong typing but verbose syntax
- Go: Performance but less AI ecosystem

### 2. Agent Framework Choice

**Decision**: LangChain + LangGraph + DeepAgents

**Context**: Need for agent orchestration, graph capabilities, and profiles

**Implications**:

- Established AI agent ecosystem
- Graph-based workflow execution
- Profile-based agent capabilities
- Integration with existing LangChain tools

**Alternatives Considered**:

- AutoGen: Microsoft-backed but less mature
- CrewAI: Simpler but less feature-rich
- LlamaIndex: Focus on retrieval but less agent-specific

### 3. Provider Strategy

**Decision**: Provider-agnostic with OpenAI-compatible API preference

**Context**: Flexibility across providers while maintaining consistency

**Implications**:

- Support for multiple LLM providers
- Consistent API patterns
- Easy switching between providers
- Reduced vendor lock-in

**Alternatives Considered**:

- Single provider: Simpler but less flexible
- Proprietary APIs: Better integration but less portability
- Custom APIs: Maximum control but higher maintenance

### 4. Human-in-the-Loop Design

**Decision**: HITL middleware with configurable interaction levels

**Context**: Need for human oversight and control

**Implications**:

- Better safety and control
- Enhanced user experience
- Complex but necessary for production use
- Requires careful UX design

**Alternatives Considered**:

- Fully automated: Simpler but less safe
- Manual intervention only: Too restrictive
- AI-only decisions: Risky for critical operations

### 5. State Management

**Decision**: Persistent state with execution workflow graphs

**Context**: Need for session continuity and complex workflows

**Implications**:

- Better user experience
- Complex workflow support
- Higher memory requirements
- More complex architecture

**Alternatives Considered**:

- Stateless: Simpler but less user-friendly
- Session-only: Limited persistence
- Database-only: More scalable but complex

### 6. Tool Architecture

**Decision**: Tool-based architecture using LangChain `@tool` decorator with MCP server integration

**Context**: Need for reusable, testable capabilities with remote server connectivity

**Rationale**:

- Follows LangChain patterns
- Easy testing and validation
- Reusable across different agents
- Clear interface contracts
- MCP server integration for extended capabilities

**Implementation**:

- MCP tools use `mcp_<server>__<tool>` naming format
- Sensitive servers (GitHub, memory) intercepted via HumanInTheLoopMiddleware
- Read-only servers (context7, docs-langchain, reference-langchain) functional without interruption
- ${VAR} placeholders in .mcp.json resolved from the gitignore .env file
- System prompt documents MCP security policy

### 7. Configuration Management

**Decision**: Pydantic v2 + pydantic-settings for configuration with .env, YAML, and JSON sources

**Context**: Need for robust configuration management across multiple sources

**Rationale**:

- Strong typing for configuration
- Support for multiple sources (.env, YAML, JSON)
- Validation and defaults
- Environment-specific configurations

**Implementation**:

- Settings loaded from `.env` file at startup
- ${VAR} placeholders expanded via `expand_env_vars()`
- .mcp.json contains placeholder secrets (not hardcoded)
- Actual secrets stored in git-ignored .env file

## Decision Process

### 1. Problem Definition

Clearly define the problem and requirements

### 2. Option Analysis

Evaluate all viable options

### 3. Trade-off Analysis

Consider pros and cons of each option

### 4. Implementation Planning

Plan for implementation and maintenance

### 5. Decision Documentation

Document the decision and rationale

## Decision Review

### Regular Reviews

- **Monthly**: Review all decisions for relevance
- **Quarterly**: Update decisions based on new information
- **Annually**: Major architecture review

### Decision Criteria

1. **Alignment**: Does it align with project goals?
2. **Feasibility**: Can it be implemented?
3. **Maintainability**: Is it easy to maintain?
4. **Scalability**: Does it scale with the project?
5. **Security**: Is it secure?

## Decision-Making Framework

### 1. Problem Statement

Clearly define the problem

### 2. Solution Options

Generate multiple viable solutions

### 3. Evaluation Criteria

Define criteria for evaluation

### 4. Analysis

Analyze each option against criteria

### 5. Selection

Select the best option

### 6. Documentation

Document the decision and rationale

## Decision Templates

### Architecture Decision

```markdown
# Architecture Decision

## Decision
[Decision description]

## Context
[Background information]

## Options Considered
[List of options]

## Rationale
[Why this option was chosen]

## Impact
[Impact on the project]

## Alternatives
[Why other options were rejected]

## Implementation
[How to implement]

## Monitoring
[How to track effectiveness]
```

### Technology Decision

```markdown
# Technology Decision

## Technology
[Technology name]

## Use Case
[Where it's used]

## Benefits
[List of benefits]

## Drawbacks
[List of drawbacks]

## Alternatives
[Other technologies considered]

## Migration
[How to migrate if needed]
```

## 📂 Codebase References

**Implementation**: `../berg_agents` (provider implementations), `../berg_agents` (tool definitions),
`../berg_agents` (configuration), `../berg_agents` (HITL middleware), `.mcp.json` (MCP server config),
`decisions/decisions-log.md` (decision documentation)

**Documentation**: `docs/CHANGELOG.md` and `decisions/decisions-log.md` (decision documentation), `README.md` (project
overview)

**Goals**: `notes/current_goals.md` (project goals and roadmap)

## Related Files

- Technical Domain (technical-domain.md)
- Business Domain (business-domain.md)
- Current Goals (notes/current_goals.md)

## Future Decisions

### Upcoming Decisions

1. **Frontend Architecture**: React vs. Vue vs. Svelte
2. **Database Strategy**: PostgreSQL vs. MongoDB vs. Redis
3. **Deployment Strategy**: Docker vs. Kubernetes vs. Serverless
4. **Monitoring**: Prometheus vs. Grafana vs. ELK stack
5. **Security**: Zero-trust vs. Defense-in-depth

### Decision Criteria for Future

1. **Project Fit**: Does it fit the project requirements?
2. **Team Skills**: Does the team have the skills?
3. **Resource Availability**: Are resources available?
4. **Long-term Viability**: Will it be viable long-term?
5. **Cost-effectiveness**: Is it cost-effective?

## Conclusion

The decisions log serves as a record of architectural and design decisions, providing context for future decisions and
ensuring consistency across the project. It helps teams understand why certain choices were made and provides a basis
for evaluating future decisions.

By documenting decisions, the project can:

1. **Maintain consistency**: Ensure all team members are on the same page
2. **Reduce risk**: Avoid repeating past mistakes
3. **Facilitate onboarding**: Help new team members understand the rationale behind decisions
4. **Support evolution**: Provide a basis for future decisions
5. **Improve communication**: Ensure clear communication about design choices

The decisions log is a living document that evolves with the project, reflecting the ongoing nature of software
development and architecture.

---

## 2026-08-28 — HITL approval display & export functionality fixes

**Decisions:**

1. **HITL approval display fix:** `HitlSurface.jsx` `extractActions()` now
   unwraps Interrupt objects (checks for `.value` + `.id` keys) before
   looking for `action_requests`. Falls back to showing raw interrupt data
   in a collapsible `<details>` element when no actions parse. Handles:
   Interrupt objects, arrays of interrupts, legacy `{tool, input}` shapes,
   and unknown shapes (treats as single action).

2. **Export functionality fix:** `web_chat_server.py` `export_thread()` now
   handles both dict and object message formats (`getattr` + `.get()`),
   shows raw data keys when no messages found for debugging, and uses
   full thread_id for checkpointer lookups (not the truncated display id).

**Rationale:** The HITL approval screen showed "Awaiting your approval" with
no context about what action was being requested. The export returned empty
for valid threads. Both caused user confusion and wasted debugging time.

**Files modified:**
- `berg_agents/ui/webapp/src/components/HitlSurface.jsx`
- `berg_agents/ui/web_chat_server.py`
- `.opencode/context/project-intelligence/learnings-webui-streaming-hitl.md`
