"use client";

import React, { useCallback, useEffect, useState } from "react";

import {
  Button,
  Card,
  Chip,
  Fieldset,
  FieldsetLegend} from "@heroui/react";
import { apiFetch, sessionId } from "./runtime";

/**
 * Types mirroring the tools this plugin's REST API returns. They are
 * the plugin's own vocabulary — the host never imports them.
 */

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
  /** Report the open-todo count for the host tool-bar badge. */
  onCount?: (open: number) => void;
  /** Switch between panel and canvas views. */
  onToggleView?: () => void;
  /** Close the surface. */
  onClose?: () => void;
  /** Layout classes from the parent (width). */
  className?: string;
  /** Inline style from the host (e.g. manifest width). */
  style?: React.CSSProperties;
}

type TodoFilter = "all" | "open" | "done";

/**
 * This plugin's identity in the host's plugin registry. The UI talks
 * only to the generic plugin-tool endpoint, so nothing here is
 * host-specific except the ids the manifest declares.
 */
const PLUGIN_ID = "berg-plugin-shared-todo";

/**
 * Call one of this plugin's tools through the host's generic
 * dispatch. Returns the tool's own string result.
 */
async function callTool(
  tool: string,
  args: Record<string, unknown> = {},
): Promise<string> {
  // Name the session so the server binds the plugin's scoped store to
  // this conversation. Without it the call falls back to the manifest
  // default and the panel shows a list no session owns.
  const sid = sessionId();
  const body = sid ? { ...args, sessionId: sid } : args;
  const resp = await apiFetch(`/api/plugins/${PLUGIN_ID}/tools/${tool}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)});
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : `HTTP ${resp.status}`,
    );
  }
  return String(data.result ?? "");
}

/**
 * Parse the Markdown-shaped output of ``list_todo_items`` into rows.
 * The tool returns a JSON array string (host-independent), so the UI
 * reads the plugin's own contract.
 */
function parseTodoItems(listResult: string): TodoItem[] {
  const start = listResult.indexOf("[");
  if (start < 0) return [];
  try {
    const parsed: unknown = JSON.parse(listResult.slice(start));
    if (!Array.isArray(parsed)) return [];
    return parsed as TodoItem[];
  } catch {
    return [];
  }
}

const STATUS_META: Record<string, { label: string; icon: string }> = {
  todo: { label: "Todo", icon: "📝" },
  in_progress: { label: "Doing", icon: "🔄" },
  done: { label: "Done", icon: "✅" }};

/**
 * Shared-todo plugin surface: side-panel list + expanded canvas view.
 * Reads the same Markdown store as the agent's todo tools via
 * the plugin's own tools through the host's generic dispatch, so
 * user edits and model edits converge on one store. Polls
 * lightly while mounted; parents force-refresh via refreshKey when a
 * todo tool call lands in the chat transcript.
 */
export function TodoSurface({
  view,
  refreshKey,
  onCount,
  onToggleView,
  onClose,
  className,
  style}: TodoPanelProps) {
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [subDrafts, setSubDrafts] = useState<Record<string, string>>({});
  const [subRenameText, setSubRenameText] = useState("");
  const [renamingSub, setRenamingSub] = useState<string | null>(null);
  const [renamingTodo, setRenamingTodo] = useState<string | null>(null);
  const [todoTitleDraft, setTodoTitleDraft] = useState("");
  const [todoDescDraft, setTodoDescDraft] = useState("");

  const fetchTodos = useCallback(async () => {
    try {
      setTodos(parseTodoItems(await callTool("list_todo_items")));
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
      await callTool("create_todo", {
        title: trimmed,
        description});
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
      await callTool("update_todo", { todo_id: todo.id, status });
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
      await callTool("delete_todo", { todo_id: todo.id });
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
      await callTool("set_subtask_done", {
        todo_id: todo.id,
        index,
        done});
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  // Rename a subtask's text (fix wording the model or the user wrote).
  const renameSubtask = async (todo: TodoItem, index: number) => {
    const text = subRenameText.trim();
    if (!text || busyId) return;
    setBusyId(`${todo.id}:sub${index}`);
    try {
      await callTool("rename_subtask", {
        todo_id: todo.id,
        index,
        text});
      setRenamingSub(null);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  // Start editing a todo's own title/description.
  const startRenameTodo = (todo: TodoItem) => {
    setRenamingTodo(todo.id);
    setTodoTitleDraft(todo.title);
    setTodoDescDraft(todo.description ?? "");
  };

  const saveTodo = async (todo: TodoItem) => {
    const title = todoTitleDraft.trim();
    if (!title || busyId) return;
    setBusyId(todo.id);
    try {
      await callTool("update_todo", {
        todo_id: todo.id,
        title,
        description: todoDescDraft});
      setRenamingTodo(null);
      await fetchTodos();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  };

  const addSubtask = async (todo: TodoItem) => {
    const text = (subDrafts[todo.id] ?? "").trim();
    if (!text || busyId) return;
    setBusyId(`${todo.id}:add`);
    try {
      await callTool("add_subtask", { todo_id: todo.id, text });
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
      await callTool("delete_subtask", { todo_id: todo.id, index });
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
      style={style}
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
                <Button
                  aria-label={`Edit ${todo.title}`}
                  isDisabled={busyId === todo.id}
                  size="sm"
                  variant="secondary"
                  onPress={() =>
                    renamingTodo === todo.id
                      ? setRenamingTodo(null)
                      : startRenameTodo(todo)
                  }
                >
                  ✏️
                </Button>
              </div>
              {renamingTodo === todo.id ? (
                <div className="flex flex-col gap-1">
                  <input
                    aria-label="Todo title"
                    className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                    onChange={(e) => setTodoTitleDraft(e.target.value)}
                    value={todoTitleDraft}
                  />
                  <textarea
                    aria-label="Todo description"
                    className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                    onChange={(e) => setTodoDescDraft(e.target.value)}
                    placeholder="Description"
                    rows={view === "canvas" ? 3 : 2}
                    value={todoDescDraft}
                  />
                  <div className="flex gap-1">
                    <Button
                      aria-label="Save todo"
                      isDisabled={!todoTitleDraft.trim()}
                      size="sm"
                      variant="primary"
                      onPress={() => void saveTodo(todo)}
                    >
                      Save
                    </Button>
                    <Button
                      aria-label="Cancel todo edit"
                      size="sm"
                      variant="secondary"
                      onPress={() => setRenamingTodo(null)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                todo.description && (
                  <p
                    className={`text-xs text-muted-foreground whitespace-pre-wrap ${view === "panel" ? "line-clamp-2" : ""}`}
                  >
                    {todo.description}
                  </p>
                )
              )}
              <Fieldset>
                <FieldsetLegend className="text-[11px] text-muted-foreground">
                  Subtasks ({(todo.subtasks ?? []).filter((s) => s.done).length}
                  /{(todo.subtasks ?? []).length})
                </FieldsetLegend>
                {(todo.subtasks ?? []).length === 0 && (
                  <p className="text-[11px] text-muted-foreground">
                    No subtasks — add one below.
                  </p>
                )}
                {/*
                  NOTE: plain buttons, not HeroUI Checkbox/CheckboxGroup.
                  HeroUI v3's Checkbox wraps React Aria's CheckboxField -
                  a standalone field - which cannot participate in
                  CheckboxGroup state and renders permanently disabled
                  with no onChange. Verified in the browser: the fibre
                  shows no isSelected/onChange ever reaching React Aria.
                  A button with aria-pressed is accessible, toggles in
                  BOTH directions, and looks identical.
                */}
                {(todo.subtasks ?? []).map((sub) => {
                  const rowBusy = busyId === `${todo.id}:sub${sub.index}`;
                  return (
                    <div
                      key={sub.index}
                      className="flex flex-col gap-1 py-0.5"
                    >
                      <div className="flex items-center gap-1.5">
                        <button
                          aria-label={`Subtask ${sub.text}`}
                          aria-pressed={sub.done}
                          className={`flex flex-1 items-center gap-1.5 rounded-md px-1 py-0.5 text-left ${
                            rowBusy
                              ? "cursor-not-allowed opacity-60"
                              : "cursor-pointer hover:bg-surface-soft"
                          }`}
                          disabled={rowBusy}
                          onClick={() =>
                            void setSubtask(todo, sub.index, !sub.done)
                          }
                          type="button"
                        >
                          <span aria-hidden>{sub.done ? "☑" : "☐"}</span>
                          <span
                            className={`flex-1 text-xs whitespace-pre-wrap ${sub.done ? "line-through text-muted-foreground" : ""}`}
                          >
                            {sub.text}
                          </span>
                        </button>
                        <Button
                          aria-label={
                            renamingSub === `${todo.id}:${sub.index}`
                              ? "Cancel rename"
                              : `Edit subtask ${sub.text}`
                          }
                          isDisabled={rowBusy}
                          size="sm"
                          variant="secondary"
                          onPress={() => {
                            const key = `${todo.id}:${sub.index}`;
                            setRenamingSub((prev) =>
                              prev === key ? null : key,
                            );
                            setSubRenameText(sub.text);
                          }}
                        >
                          ✏️
                        </Button>
                        <Button
                          aria-label={`Delete subtask ${sub.text}`}
                          isDisabled={rowBusy}
                          size="sm"
                          variant="secondary"
                          onPress={() => void deleteSubtask(todo, sub.index)}
                        >
                          ✕
                        </Button>
                      </div>
                      {renamingSub === `${todo.id}:${sub.index}` && (
                        <div className="flex gap-1 pl-6">
                          <input
                            aria-label="Subtask text"
                            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-0.5 text-xs"
                            onChange={(e) =>
                              setSubRenameText(e.target.value)
                            }
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                void renameSubtask(todo, sub.index);
                              }
                              if (e.key === "Escape") setRenamingSub(null);
                            }}
                            value={subRenameText}
                          />
                          <Button
                            aria-label="Save subtask text"
                            size="sm"
                            variant="primary"
                            onPress={() =>
                              void renameSubtask(todo, sub.index)
                            }
                          >
                            Save
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}
                <div className="mt-1 flex gap-1">
                  <input
                    aria-label={`New subtask for ${todo.title}`}
                    name={`new-subtask-${todo.id}`}
                    id={`new-subtask-${todo.id}`}
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
            name="new-todo-title"
            id="new-todo-title"
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
            name="new-todo-description"
            id="new-todo-description"
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

export default TodoSurface;
