"use client";

import { useCallback, useEffect, useState } from "react";

import {
  Button,
  Card,
  Checkbox,
  CheckboxGroup,
  Chip,
  Fieldset,
  FieldsetLegend} from "@heroui/react";
import { API_BASE } from "@/envConfig";

/**
 * Todo tool names exposed by the shared-todo pilot plugin. The App
 * watches the chat transcript for these to refresh the panel when
 * the agent changes todos.
 */
export const TODO_TOOL_NAMES = [
  "create_todo",
  "list_todos",
  "update_todo",
  "complete_todo",
  "delete_todo",
  "add_subtask",
  "set_subtask_done",
  "delete_subtask"];

export interface TodoSubtask {
  index: number;
  text: string;
  done: boolean;
}

export interface TodoItem {
  id: string;
  title: string;
  status: string;
  description?: string;
  subtasks?: TodoSubtask[];
  file: string;
}

export interface TodoPanelProps {
  /** Side-panel (narrow) or canvas (wide) presentation. */
  view: "panel" | "canvas";
  /** Bump to force a refetch (e.g. after an agent todo tool call). */
  refreshKey: number;
  /** Report the open-todo count for the toggle badge. */
  onCount?: (open: number) => void;
  /** Switch between panel and canvas views. */
  onToggleView?: () => void;
  /** Close the surface. */
  onClose?: () => void;
  /** Extra layout classes from the parent (width). */
  className?: string;
}

type TodoFilter = "all" | "open" | "done";

const STATUS_META: Record<string, { label: string; icon: string }> = {
  todo: { label: "Todo", icon: "📝" },
  in_progress: { label: "Doing", icon: "🔄" },
  done: { label: "Done", icon: "✅" }};

/**
 * Shared-todo plugin surface: side-panel list + expanded canvas view.
 * Reads the same Markdown store as the agent's todo tools via
 * /api/plugins/todos, so user edits and model edits converge. Polls
 * lightly while mounted; parents force-refresh via refreshKey when a
 * todo tool call lands in the chat transcript.
 */
export function TodoPanel({
  view,
  refreshKey,
  onCount,
  onToggleView,
  onClose,
  className}: TodoPanelProps) {
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [subDrafts, setSubDrafts] = useState<Record<string, string>>({});

  const fetchTodos = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/plugins/todos`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setTodos(Array.isArray(data.todos) ? data.todos : []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void fetchTodos();
  }, [fetchTodos, refreshKey]);

  // Light polling keeps user edits in another tab and agent edits
  // visible without manual refreshes.
  useEffect(() => {
    const timer = window.setInterval(() => void fetchTodos(), 15000);
    return () => window.clearInterval(timer);
  }, [fetchTodos]);

  const openCount = todos.filter((t) => t.status !== "done").length;
  useEffect(() => {
    onCount?.(openCount);
  }, [openCount, onCount]);

  const visible = todos.filter((t) => {
    if (filter === "open") return t.status !== "done";
    if (filter === "done") return t.status === "done";
    return true;
  });

  const createTodo = async () => {
    const trimmed = title.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      const resp = await fetch(`${API_BASE}/api/plugins/todos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed, description })});
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setTitle("");
      setDescription("");
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  };

  const setStatus = async (todo: TodoItem, status: string) => {
    if (todo.status === status || busyId) return;
    setBusyId(todo.id);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/todos/${encodeURIComponent(todo.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status })},
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const deleteTodo = async (todo: TodoItem) => {
    if (busyId) return;
    setBusyId(todo.id);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/todos/${encodeURIComponent(todo.id)}`,
        { method: "DELETE" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const setSubtask = async (todo: TodoItem, index: number, done: boolean) => {
    if (busyId) return;
    setBusyId(`${todo.id}:sub${index}`);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/todos/${encodeURIComponent(todo.id)}/subtasks/${index}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done })},
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  // CheckboxGroup reports the whole checked set; a click changes exactly
  // one entry, so diff against the previous set to find the toggle.
  const onSubtaskGroupChange = (todo: TodoItem, checked: string[]) => {
    const prev = new Set(
      (todo.subtasks ?? []).filter((s) => s.done).map((s) => String(s.index)),
    );
    const next = new Set(checked);
    const added = [...next].find((id) => !prev.has(id));
    const removed = [...prev].find((id) => !next.has(id));
    const changed = added ?? removed;
    if (changed === undefined) return;
    void setSubtask(todo, Number(changed), added !== undefined);
  };

  const addSubtask = async (todo: TodoItem) => {
    const text = (subDrafts[todo.id] ?? "").trim();
    if (!text || busyId) return;
    setBusyId(`${todo.id}:add`);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/todos/${encodeURIComponent(todo.id)}/subtasks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text })},
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setSubDrafts((prev) => ({ ...prev, [todo.id]: "" }));
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const deleteSubtask = async (todo: TodoItem, index: number) => {
    if (busyId) return;
    setBusyId(`${todo.id}:sub${index}`);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/todos/${encodeURIComponent(todo.id)}/subtasks/${index}`,
        { method: "DELETE" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card
      className={`mb-2 flex min-h-0 flex-col ${className ?? ""}`}
      variant="default"
    >
      <Card.Header>
        <Card.Title>📋 Shared Todos</Card.Title>
        <Card.Description>
          {loading ? "Loading…" : `${openCount} open · ${todos.length} total`}
        </Card.Description>
        <span className="flex-1" />
        {onToggleView && (
          <Button
            aria-label={
              view === "panel" ? "Expand to canvas" : "Shrink to panel"
            }
            size="sm"
            variant="secondary"
            onPress={onToggleView}
          >
            {view === "panel" ? "⛶ Canvas" : "◫ Panel"}
          </Button>
        )}
        <Button
          aria-label="Refresh todos"
          size="sm"
          variant="secondary"
          onPress={() => void fetchTodos()}
        >
          ↻
        </Button>
        {onClose && (
          <Button
            aria-label="Close todos"
            size="sm"
            variant="secondary"
            onPress={onClose}
          >
            ✕
          </Button>
        )}
      </Card.Header>
      <Card.Content className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {error && <p className="text-xs text-red-500">{error}</p>}
        <div className="flex gap-1">
          {(["all", "open", "done"] as TodoFilter[]).map((f) => (
            <Button
              key={f}
              aria-label={`Show ${f} todos`}
              size="sm"
              variant={filter === f ? "primary" : "secondary"}
              onPress={() => setFilter(f)}
            >
              {f === "all" ? "All" : f === "open" ? "Open" : "Done"}
            </Button>
          ))}
        </div>
        {visible.length === 0 && !loading && !error && (
          <p className="text-xs text-muted-foreground">
            {todos.length === 0
              ? "No todos yet — create one below or ask the agent."
              : `Nothing ${filter === "all" ? "" : filter} here.`}
          </p>
        )}
        {visible.map((todo) => {
          const meta = STATUS_META[todo.status] ?? {
            label: todo.status,
            icon: "❓"};
          return (
            <div
              key={todo.id}
              className="flex flex-col gap-1 rounded-md border border-border px-2 py-1.5"
            >
              <div className="flex items-center gap-1.5">
                <span className="flex-1 text-sm font-medium">{todo.title}</span>
                <Chip size="sm" variant="soft">
                  {meta.icon} {meta.label}
                </Chip>
                <Button
                  aria-label={`Delete ${todo.title}`}
                  isDisabled={busyId === todo.id}
                  size="sm"
                  variant="secondary"
                  onPress={() => void deleteTodo(todo)}
                >
                  🗑
                </Button>
              </div>
              {todo.description && (
                <p
                  className={`text-xs text-muted-foreground whitespace-pre-wrap ${view === "panel" ? "line-clamp-2" : ""}`}
                >
                  {todo.description}
                </p>
              )}
              <Fieldset>
                <FieldsetLegend className="text-[11px] text-muted-foreground">
                  Subtasks ({(todo.subtasks ?? []).filter((s) => s.done).length}
                  /{(todo.subtasks ?? []).length})
                </FieldsetLegend>
                <CheckboxGroup
                  aria-label={`Subtasks of ${todo.title}`}
                  isDisabled={busyId !== null}
                  onChange={(checked) =>
                    onSubtaskGroupChange(todo, checked as string[])
                  }
                  value={(todo.subtasks ?? [])
                    .filter((s) => s.done)
                    .map((s) => String(s.index))}
                >
                  {(todo.subtasks ?? []).map((sub) => (
                    <div key={sub.index} className="flex items-center gap-1">
                      <Checkbox value={String(sub.index)} className="flex-1">
                        <span
                          className={`text-xs ${sub.done ? "line-through text-muted-foreground" : ""}`}
                        >
                          {sub.text}
                        </span>
                      </Checkbox>
                      <Button
                        aria-label={`Delete subtask ${sub.text}`}
                        isDisabled={busyId !== null}
                        size="sm"
                        variant="secondary"
                        onPress={() => void deleteSubtask(todo, sub.index)}
                      >
                        ✕
                      </Button>
                    </div>
                  ))}
                </CheckboxGroup>
                <div className="mt-1 flex gap-1">
                  <input
                    aria-label={`New subtask for ${todo.title}`}
                    className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-0.5 text-xs"
                    onChange={(e) =>
                      setSubDrafts((prev) => ({
                        ...prev,
                        [todo.id]: e.target.value}))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void addSubtask(todo);
                    }}
                    placeholder="New subtask… (Enter to add)"
                    value={subDrafts[todo.id] ?? ""}
                  />
                  <Button
                    aria-label={`Add subtask to ${todo.title}`}
                    isDisabled={
                      !(subDrafts[todo.id] ?? "").trim() || busyId !== null
                    }
                    size="sm"
                    variant="secondary"
                    onPress={() => void addSubtask(todo)}
                  >
                    ＋
                  </Button>
                </div>
              </Fieldset>
              <div className="flex gap-1">
                {Object.entries(STATUS_META).map(([status, m]) => (
                  <Button
                    key={status}
                    aria-label={`Mark ${todo.title} as ${m.label}`}
                    isDisabled={busyId === todo.id}
                    size="sm"
                    variant={todo.status === status ? "primary" : "secondary"}
                    onPress={() => void setStatus(todo, status)}
                  >
                    {m.icon} {m.label}
                  </Button>
                ))}
              </div>
            </div>
          );
        })}
        <div className="mt-1 flex flex-col gap-1 border-t border-border pt-2">
          <input
            aria-label="New todo title"
            className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void createTodo();
            }}
            placeholder="New todo… (Enter to add)"
            value={title}
          />
          <textarea
            aria-label="New todo description"
            className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            rows={view === "canvas" ? 3 : 1}
            value={description}
          />
          <Button
            isDisabled={!title.trim() || creating}
            size="sm"
            variant="primary"
            onPress={() => void createTodo()}
          >
            ＋ Add todo
          </Button>
        </div>
      </Card.Content>
    </Card>
  );
}

export default TodoPanel;
