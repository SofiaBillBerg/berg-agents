# Context-Management Improvements for `berg_agents`

A **non-invasive proposal** for how `berg_agents` should manage context using the
already-installed Pydantic AI tooling (`pydantic_ai>=2.30`, `pydantic_ai_harness`).
**Nothing in `berg_agents/` is edited.** Everything lives here, in `suggestions/`,
so the existing application code keeps working unchanged while we explore, test,
and adopt incrementally.

---

## TL;DR

| #   | What                                                                                                                             | File                         |
| --- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- |
| 1   | **Current-state audit** — where context handling breaks today                                                                    | `01_current_state.md`        |
| 2   | **Design principles** — goals, constraints, and the "why"                                                                        | `02_design_principles.md`    |
| 3   | **`SessionContext`** — one typed, immutable model that replaces the fragmented raw dicts                                         | `03_session_context.py`      |
| 4   | **Deps classes** — `TaskContextDeps` / `SessionContextDeps` so `RunContext.deps` is actually used                                | `04_context_deps.py`         |
| 5   | **`ContextProvider` protocol** — pluggable save/load (InMemory / File / future Redis/SQLite), evolving the Checkpointer contract | `05_context_provider.py`     |
| 6   | **Context middleware** — tracing, usage-limits awareness, auto-snapshot hooks                                                    | `06_context_middleware.py`   |
| 7   | **Integration examples** — runnable snippets for the chat agent, the harness, and `BergLoop`                                     | `07_integration_examples.md` |
| 8   | **Roadmap** — phased adoption, backward-compat notes, team memo                                                                  | `08_roadmap.md`              |

---

## The three problems this solves

1. **`RunContext.deps` is declared but ignored.** Every Pydantic AI agent in
   `berg_agents/agents/*` declares a `deps_type` (`PlannerDeps`,
   `ImplementationDeps`) and annotates its tools with `ctx: RunContext[...Deps]` —
   but the tool bodies do `_ = ctx` everywhere.
   The deps are never read, and the
   `Agent` instances are never constructed with `deps=...`, so the dependency
   injection feature Pydantic AI is designed around does nothing in this project.
   **Fix:** real deps classes + a deps registry + `agent.run(..., deps=...)`.

2. **Context is scattered across incompatible shapes.** The harness carries a
   `dict` task with `metadata: dict[str, Any]`; the interface layer has a
   `TaskContext` dataclass; the loop stores a JSON snapshot with `messages`,
   `step`, `tool_calls`, `pending_hitl`; Pydantic AI's run carries
   `RunContext.messages`, `RunContext.usage`, `RunContext.usage_limits`.
   Nothing
   is a single source of truth, and the JSON snapshot format is implicit, brittle,
   and easy to corrupt on version changes.
   **Fix:** one `SessionContext` Pydantic
   model that unifies all of these with a version field and typed round-trip.

3. **No hooks for cross-cutting concerns.** There's no place for tracing,
   usage-budget awareness, or automatic checkpointing that sees the _same_ context
   object the agents use.
   The checkpointing code and the Pydantic AI run are two
   separate tracks that don't talk to each other.
   **Fix:** a
   `ContextProvider` protocol plus optional middleware that reads `RunContext`
   (usage, limits, model, messages) and persists a canonical snapshot per
   `thread_id`/`session_id`.

---

## How to use this directory

```bash
cd /home/nvidia/code-projects/berg-agents/suggestions

# 1. Read the audit first (it's the evidence base)
cat 01_current_state.md

# 2. Then the design principles
cat 02_design_principles.md

# 3. Try the code — it's importable on its own (no berg_agents source touched)
python3 - <<'EOF'
from context_deps import TaskContextDeps, SessionContextDeps
from context_provider import InMemoryProvider
print("imports OK")
EOF
```

The `.py` files are written to be **self-contained and importable** without
modifying any existing `berg_agents/` file.
Where they need to interop with the
existing runtime (checkpointing, tools), they **wrap** the existing pieces rather
than replace them — e.g. `context_provider.py` can _optionally_ bridge to the
existing `Checkpointer` so the web UI and TUI continue to resume unchanged while
new code adopts `ContextProvider`.

---

## Non-goals (explicitly out of scope)

- ❌ No refactoring of `berg_agents/` itself.
- ❌ No breaking changes to the `Harness.execute_task()` return shape.
- ❌ No changes to `BergLoop` internals (that's a separate, larger effort).
- ❌ No migration guides for external frameworks (LangChain, ADK, etc.) — those
  are documented separately.
- ❌ No tests.
  Testing is deliberately low-priority per the project guidance;
  the `.py` files are written so they can be `pytest`-imported and checked later.

---

## Questions to answer before adopting anything

1. Should `RunContext.deps` become the single authoritative source of per-agent
   state, or should it stay read-only metadata with a separate `SessionContext`?
2. What is the desired default persistence for `SessionContext` — in-memory only,
   file-per-session, or SQLite/Redis?
   (The `ContextProvider` protocol answers this
   without code changes.)
3. Do we want the checkpointing layer and the Pydantic AI run to converge on one
   snapshot shape, or keep them parallel with a migration adapter?

The `08_roadmap.md` file proposes a phased path that lets us answer these one at a
time, with each phase opt-in and reversible.
