# 02 — Design Principles for the Pydantic AI Context Layer

This doc sets the goals and constraints for any context-layer change. It's the
filter every idea in `suggestions/` is judged against.

---

## 1. Goals (in priority order)

### G1 — One canonical, typed context object

There must be exactly **one** object that owns the state of a thread/session:
task identity, messages, complexity, risk, usage, model, HITL state, session
variables. Everything else (checkpoints, results, API responses) is either a
projection of it or a legacy shape kept for compatibility.

### G2 — `RunContext.deps` becomes the _live_ per-run view

Pydantic AI's dependency injection is the mechanism designed for exactly this.
Once agents start consuming `ctx.deps`, the run context becomes the single
source of truth for what the _agent_ sees right now.

### G3 — Persistence is pluggable, not baked in

The layer that writes context to disk/DB is a **protocol**, so the default
backend can swap without touching agent code. This is how we upgrade from
in-memory → file-per-session → Redis/SQLite without a code freeze.

### G4 — Snapshot format is self-describing and migrable

Every persisted state carries a version; migrations run at load time instead of
at every write. This is the fix for the brittle `"schema_version": 1` we have
today.

### G5 — Zero disruption to the existing runtime

Nothing in `berg_agents/` changes. Every new piece is opt-in, importable on its
own, and able to wrap the existing `Checkpointer` / `ToolSpec` / `BergLoop` so
the web UI, TUI, and CLI keep working unchanged.

### G6 — Testable in isolation

Each component can be exercised by import + a handful of assertions without
spinning up an LLM, a server, or the harness.

---

## 2. Constraints

- **No editing existing files.** `berg_agents/` is read-only.
- **No test files.** (Low priority per project guidance.)
- **Python 3.12** only (the project's minimum).
- **Pydantic v2** only (`pydantic>=2.13`).
- **Pydantic AI 2.x** only (`pydantic_ai>=2.30`), matching what's installed
  (`2.51.0`). Use only the public API: `Agent`, `RunContext`, `Tool`,
  `Toolset`, `AgentCapability`, `AgentRetries`, `CancellationToken`.
- **Framework-agnostic core stays that way.** Context middleware must not import
  `berg_agents.core.loop.BergLoop` or the harness. The middleware hooks operate
  on `RunContext` and the `ContextProvider` — pure pydantic_ai + stdlib.
- **Preserve wire compatibility.** The harness `execute_task` dict and the
  checkpoint snapshot must keep returning the same keys so nothing in the UI
  breaks.

---

## 3. Named concepts (vocabulary)

| Concept                 | Meaning                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| **`SessionContext`**    | The canonical, typed, immutable model of a thread's full state.                                   |
| **`ContextDeps`**       | The per-run dependency payload injected via `Agent(..., deps=ContextDeps)` / `ctx.deps`.          |
| **`ContextProvider`**   | The pluggable persistence protocol (`load` / `save` / `dump`).                                    |
| **`ContextMiddleware`** | Optional hooks that observe and mutate the context around a run (tracing, limits, auto-snapshot). |
| **`ContextRegistry`**   | (Optional) a deps-class registry keyed by agent name for factory-style construction.              |

---

## 4. Model shape: SessionContext

The session context unifies the four fragmented shapes into one dataclass.
Pydantic `BaseModel` for validation + JSON schema generation (useful for
API/UI) or frozen dataclass for immutability — we offer both, with a
`SessionContextModel` as the authoritative typed source and a frozen view for
runs.

```python
@dataclass(frozen=True)
class SessionContext:
    schema_version: int = 1
    thread_id: str
    task_id: str
    description: str
    task_type: str
    complexity: str  # trivial|standard|complex|critical
    risk_level: str  # low|medium|high|critical
    model_id: str | None
    messages: list[dict[str, Any]]          # full conversation so far
    step: int = 0
    tool_calls: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    session_vars: dict[str, Any] = field(default_factory=dict)
    pending_hitl: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str          # ISO timestamp
    updated_at: str          # ISO timestamp
```

### Why each field

- `schema_version` → G4: enables migration at load time.
- `usage` → G5: fills the gap in the current snapshot (no usage/limits anywhere).
- `session_vars` → G5: replaces ad-hoc `metadata` for per-session mutable state;
  keeps the canonical context extensible without touching its schema.
- `created_at`/`updated_at` → auditability; trivial to surface in the UI.

### Round-trip guarantee

- `SessionContext.model_dump()` ↔ JSON file ↔ `SessionContext.model_validate(...)`.
- `SessionContext.from_snapshot(dict)` for migration from the legacy
  `core.checkpoint.make_snapshot` shape.
- `SessionContext.to_snapshot()` produces a **forward-compatible** snapshot that
  the legacy reader can still digest.

---

## 5. Deps model: `ContextDeps`

Two levels, mirroring the existing pattern but _actually used_:

```python
@dataclass(frozen=True)
class TaskContextDeps:
    """What a *single* agent run needs. Replaces planner/implementation deps.
    """
    workspace_root: Path
    task_type: str
    complexity: str
    session: "SessionContext"          # shared, read-only reference
    provider_cfg: dict[str, Any]       # resolved model/provider kwargs

@dataclass(frozen=True)
class ContextDeps:
    """Top-level deps; `TaskContextDeps` is nested per-agent.
    """
    agent_name: str
    task: dict[str, Any]
    context: ContextDeps | TaskContextDeps
```

**Change pattern vs. today:** the existing tools take `ctx: RunContext[ImplDeps]`
and do `_ = ctx` or `ctx.deps.workspace_root`. The new pattern passes a real
`ContextDeps` at run time: `agent.run(prompt, deps=ContextDeps(agent_name="...",
context=TaskContextDeps(...)))`. Because everything is frozen, multiple agents in
one run can share the same `SessionContext` without aliasing bugs.

---

## 6. Provider protocol

```python
class ContextProvider(Protocol):
    async def load(self, thread_id: str) -> SessionContext | None: ...
    async def save(self, thread_id: str, ctx: SessionContext) -> None: ...
    async def delete(self, thread_id: str) -> bool: ...
    async def list_ids(self) -> list[str]: ...

class InMemoryProvider(ContextProvider): ...   # tests, CLI one-shot
class FileProvider(ContextProvider): ...       # one .json per thread; evolves Checkpointer
```

**Bridge note:** `FileProvider` can be implemented _on top of_ the existing
`Checkpointer` by reading/writing the legacy snapshot, translating to/from
`SessionContext` in both directions. This lets us:

- keep the web UI/TUI resuming via the old path, AND
- have new code call `ContextProvider.save(thread_id, new_ctx)`.

The bridge lives in `suggestions/` and is opt-in — no existing behavior changes.

---

## 7. Middleware hooks

Optional async hooks that receive the live `RunContext[ContextDeps]`:

```python
class ContextMiddleware:
    async def on_run_start(self, ctx: RunContext[ContextDeps]) -> None: ...
    async def on_tool_call(self, ctx: RunContext[ContextDeps], spec: ToolCallEvent) -> None: ...
    async def on_run_end(self, ctx: RunContext[ContextDeps], result: AgentRunResult) -> None: ...
    async def on_usage_budget_near_limit(self, ctx: RunContext[ContextDeps],
                                         usage: RunUsage, limits: UsageLimits) -> None: ...
```

**What this buys (G5):**

- A tracing middleware (Logfire/OpenTelemetry) that logs the _same_ `SessionContext`
  the agent uses — no separate snapshot duplication.
- A usage-limits middleware that reads `ctx.usage_limits` / `ctx.usage` (which the
  existing code never inspects) and can pre-emptively stop before hitting
  `request_limit=50`.
- An auto-snapshot middleware that calls `ContextProvider.save` at each step
  boundary instead of the loop's hand-rolled `_persist_snapshot`.

---

## 8. What we deliberately do NOT do

- ❌ Don't replace `BergLoop`'s `_persist_snapshot` / `_load_snapshot`.
  (They keep working; the middleware is an additive, opt-in layer.)
- ❌ Don't force `Harness.execute_task` to return `AgentResult`. The return
  shape is kept for compatibility; the new layer exposes `SessionContext`
  separately.
- ❌ Don't touch `ToolSpec`/`make_tool_spec`. The deps are injected at `agent.run`
  time, not inside tools.

---

## 9. Validation checklist for every suggestion

Before a file in `suggestions/` is considered "adoptable":

- [ ] Does it create **one** canonical `SessionContext` without duplicating state?
- [ ] Does it make `RunContext.deps` read something useful?
- [ ] Is persistence behind a `ContextProvider` protocol, not a hard-coded path?
- [ ] Can it be imported with `python3 - <<EOF ... EOF` and pass basic checks?
- [ ] Does importing it change nothing in `berg_agents/`?
- [ ] Does the snapshot schema carry `schema_version` and a migration path?

---

**Next:** `03_session_context.py` implements the canonical model; `04_context_deps.py`
implements the deps classes.
