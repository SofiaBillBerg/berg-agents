# 01 — Current State: How Context Is Handled Today

This file is a **factual audit** of the existing code. Nothing is argued for or
against yet — just what the code does, sourced from the repo at
`berg_agents/`. Every claim below is backed by a specific file/line.

---

## 1. Context shapes are fragmented across four independent layers

### 1.1 `core.interface.TaskContext` — the agent-facing contract

**File:** `berg_agents/core/interface.py`

```python
@dataclass
class TaskContext:
    task_id: str
    description: str
    task_type: str = "implementation"
    complexity: TaskComplexity = TaskComplexity.STANDARD
    risk_level: RiskLevel = RiskLevel.LOW
    metadata: dict[str, Any] = field(default_factory=dict)
```

- Used by `AbstractAgent.execute(task, context: TaskContext, model=None)` and by
  `Planner.execute(...)`.
- It is **only used for the harness layer**, never for message history, never for
  the LLM run, never for the checkpoint. `metadata` is an untyped catch-all.

### 1.2 `core.interface.TaskContext` / `AgentResult` — result shape

**File:** `berg_agents/core/interface.py`

```python
@dataclass
class AgentResult:
    success: bool
    output: Any = None
    error: str | None = None
    needs_human_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    model_used: str | None = None
    tokens_used: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

`AgentResult.to_dict()` is the serializable view — again `metadata` is an
untyped dict.

### 1.3 `harness/orchestrator.py` — the harness carries a raw `dict`

**File:** `berg_agents/core/harness/orchestrator.py`, `execute_task`

```python
def execute_task(self, task: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
    description = str(task.get("description", ""))
    task_type = str(task.get("task_type", "implementation") or "implementation")
    metadata = task.get("metadata") or {}
    ...
    # result is a hand-built dict, never a TaskContext/AgentResult
    result: dict[str, Any] = {
        "status": "completed",
        "task_id": resolved_id,
        "task_type": task_type,
        "complexity": complexity.value,
        "risk_level": verdict.risk_level,
        "confidence": confidence,
        "selected_agent": selected,
        "model": effective_model,
        "plan": plan,
        "implementation": implementation,
        "curation": curation,
        "inference_attempted": inference_attempted}
```

**Finding:** the "real" work happens with **plain `dict`**, and `TaskContext`
exists only on the `AbstractAgent.execute` signature. The two are not the same
object.

### 1.4 `core.checkpoint` — the loop snapshot is a hand-rolled JSON shape

**File:** `berg_agents/core/checkpoint.py`, `make_snapshot`

```python
def make_snapshot(
    *,
    thread_id: str,
    messages: Sequence[Mapping[str, Any]],
    step: int,
    tool_calls: int,
    pending_hitl: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "messages": [dict(m) for m in messages],
        "step": step,
        "tool_calls": tool_calls,
        "pending_hitl": (dict(pending_hitl) if pending_hitl is not None else None),
        "metadata": dict(metadata) if metadata is not None else {},
        "schema_version": 1}
```

**Finding:** the snapshot schema is defined by convenience, not by a schema
object. `"schema_version": 1` is present but there is **no migration logic** —
version bumping this dict is manual and error-prone. Note also the schema has
`metadata` but no place for **usage / token counts / model id / session vars** —
those live only in `RunContext` inside a Pydantic AI run, never in the snapshot.

### 1.5 Pydantic AI's own run context — a fifth shape

**File:** `pydantic_ai` (installed `2.51.0`)

```python
@dataclass(frozen=True)
class RunContext(Generic[RunContextAgentDepsT]):
    deps: RunContextAgentDepsT
    model: AbstractModel
    usage: RunUsage
    _model_id: str | None = None
    usage_limits: UsageLimits | None = None
    agent: Agent[RunContextAgentDepsT, Any] | None = None
    prompt: str | Sequence[UserContent] | None = None
    messages: list[ModelMessage] = field(default_factory=list)
    validation_context: Any = None
    tracer: Tracer = field(default_factory=NoOpTracer)
    ...
```

**Finding:** this is the _only_ place where usage, limits, model id, and the live
message list coexist. It is invisible to the checkpoint layer and invisible to
the harness `dict`.

---

## 2. `RunContext.deps` is declared everywhere but never used

Every Pydantic AI agent module declares a deps type and annotates tools with
`ctx: RunContext[...Deps]` — but the tool bodies ignore them:

**`berg_agents/agents/planner.py`** — `PlannerDeps`, tools do `_ = ctx`:

```python
@planner_agent.tool
def decompose_task(ctx: RunContext[PlannerDeps], description: str, ...) -> str:
    # Context is unused beyond the required first param; the plan itself is fully deterministic.
    _ = ctx
```

**`berg_agents/agents/implementation.py`** — `ImplementationDeps`:

```python
@agent.tool
def read_file(ctx: RunContext[ImplementationDeps], file_path: str) -> str:
    root = ctx.deps.workspace_root or "."
    ...
```

Only `implementation.py`'s tools _read_ `ctx.deps.workspace_root`; the planner
and guardian tools do `_ = ctx`. The agents are constructed with **no** `deps=...`
argument, so `ctx.deps` is effectively a synthetic stub.

**Findings:**

1. The dependency-injection capability Pydantic AI built this around is
   **dormant**.
2. Where deps _are_ used, they're passed in as `ctx.deps.workspace_root`, but the
   `Agent` instances are built once at import time (`planner_agent`,
   `implementation_agent` module globals) with a _fixed_ `workspace_root` baked
   into the tool closures — not injected per run. This makes workspace resolution
   static instead of per-thread.
3. `ImplementationDeps` carries `workspace_root, complexity, task_type` — but
   `complexity` and `task_type` are already in the task dict / model routing, so
   there's duplication between the harness `dict`, the `TaskContext`, the deps,
   and the message history.

---

## 3. What ISN'T in scope for this proposal (per project guidance)

- ❌ No editing of `berg_agents/` files.
- ❌ No refactoring of `BergLoop`, `Harness`, or `ToolSpec` internals.
- ❌ No tests (explicitly low-priority).
- ✅ Only new files in `suggestions/`.

---

## 4. Evidence table

| Layer           | Shape                                     | Location                  | Serialized?   | Typed? | Versioned?   | Shared with agents?         |
| --------------- | ----------------------------------------- | ------------------------- | ------------- | ------ | ------------ | --------------------------- |
| Agent contract  | `TaskContext` / `AgentResult` (dataclass) | `core/interface.py`       | `.to_dict()`  | ✅     | ❌           | ✅ (harness only)           |
| Harness run     | plain `dict`                              | `harness/orchestrator.py` | ✅ (JSON-ish) | ❌     | ❌           | ✅                          |
| Loop snapshot   | plain `dict` + `"schema_version": 1`      | `core/checkpoint.py`      | ✅ (JSON)     | ❌     | 🟡 only name | ❌                          |
| Pydantic AI run | `RunContext` (frozen dataclass)           | `pydantic_ai`             | ❌            | ✅     | ✅           | ✅ (via `ctx`)              |
| Agent deps      | `PlannerDeps`, `ImplementationDeps`       | `agents/*.py`             | ❌            | ✅     | ✅           | 🟡 declared, mostly ignored |

---

## 5. Concrete pain points (as evidenced)

1. **No single canonical context object.** Four incompatible shapes describe one
   conversation; none is authoritative.
2. **`RunContext.deps` is unused.** The pydantic-ai deps feature is dormant.
3. **Snapshot schema is implicit.** Adding a field (e.g. `tokens_used`) requires
   hand-editing `make_snapshot` plus every `get()`/`resume` reader.
4. **No version migration.** `schema_version: 1` exists but nothing ever bumps
   or interprets it.
5. **Usage/limits invisible outside the run.** `RunContext.usage` /
   `usage_limits` cannot be checkpointed, surfaced to the UI, or enforced
   across resume.
6. **Per-thread workspace is static.** `workspace_root` is captured in closures
   at import, not injected per run/thread.

**Next:** `02_design_principles.md` argues what the solution should look like.
