"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Streamdown } from "streamdown";

import { apiFetch, sessionId } from "./runtime";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle} from "@/components/ui/card";
import { FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

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

const PLUGIN_ID = "berg-plugin-shared-todo";

async function callTool(
  tool: string,
  args: Record<string, unknown> = {},
): Promise<string> {
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

  const startRenameTodo = (todo: TodoItem) => {
    setRenamingTodo(todo.id);
    setTodoTitleDraft(todo.title);
    setTodoDescDraft(todo.description ?? "");
  };

  const saveTodo = async (todo: TodoItem) => {
    const nextTitle = todoTitleDraft.trim();
    if (!nextTitle || busyId) return;
    setBusyId(todo.id);
    try {
      await callTool("update_todo", {
        todo_id: todo.id,
        title: nextTitle,
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
    >
      <CardHeader className="flex flex-row items-center gap-2 space-y-0">
        <div className="min-w-0 flex-1">
          <CardTitle>📋 Shared Todos</CardTitle>
          <CardDescription>
            {loading ? "Loading…" : `${openCount} open · ${todos.length} total`}
          </CardDescription>
        </div>
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
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex gap-1">
          {(["all", "open", "done"] as TodoFilter[]).map((f) => (
            <Button
              key={f}
              aria-label={`Show ${f} todos`}
              size="sm"
              variant={filter === f ? "default" : "secondary"}
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
              className="flex flex-col gap-1.5 rounded-md border border-border px-2.5 py-2"
            >
              <div className="flex items-center gap-1.5">
                <span className="flex-1 text-sm font-medium">{todo.title}</span>
                <Badge variant="secondary">
                  {meta.icon} {meta.label}
                </Badge>
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
                <div className="flex flex-col gap-1.5">
                  <Input
                    aria-label="Todo title"
                    className="h-8 text-sm"
                    value={todoTitleDraft}
                    onChange={(e) => setTodoTitleDraft(e.target.value)}
                  />
                  <Textarea
                    aria-label="Todo description"
                    className="min-h-14 text-sm"
                    placeholder="Description"
                    rows={view === "canvas" ? 3 : 2}
                    value={todoDescDraft}
                    onChange={(e) => setTodoDescDraft(e.target.value)}
                  />
                  <div className="flex gap-1">
                    <Button
                      aria-label="Save todo"
                      isDisabled={!todoTitleDraft.trim()}
                      size="sm"
                      variant="default"
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
                  <div
                    className={`prose prose-xs dark:prose-invert max-w-none text-xs text-muted-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 ${view === "panel" ? "line-clamp-2" : ""}`}
                  >
                    <Streamdown>{todo.description}</Streamdown>
                  </div>
                )
              )}

              <FieldSet className="gap-1">
                <FieldLegend
                  className="mb-0 text-[11px] text-muted-foreground"
                  variant="label"
                >
                  Subtasks ({(todo.subtasks ?? []).filter((s) => s.done).length}
                  /{(todo.subtasks ?? []).length})
                </FieldLegend>

                {(todo.subtasks ?? []).length === 0 && (
                  <p className="text-[11px] text-muted-foreground">
                    No subtasks — add one below.
                  </p>
                )}

                {(todo.subtasks ?? []).map((sub) => {
                  const rowBusy = busyId === `${todo.id}:sub${sub.index}`;
                  return (
                    <div key={sub.index} className="flex flex-col gap-1 py-0.5">
                      <div className="flex items-center gap-1.5">
                        <button
                          aria-label={`Subtask ${sub.text}`}
                          aria-pressed={sub.done}
                          className={`flex flex-1 items-center gap-1.5 rounded-md px-1 py-0.5 text-left ${
                            rowBusy
                              ? "cursor-not-allowed opacity-60"
                              : "cursor-pointer hover:bg-muted"
                          }`}
                          disabled={rowBusy}
                          type="button"
                          onClick={() =>
                            void setSubtask(todo, sub.index, !sub.done)
                          }
                        >
                          <span aria-hidden>{sub.done ? "☑" : "☐"}</span>
                          <div
                            className={`prose prose-xs dark:prose-invert min-w-0 flex-1 text-xs [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 ${sub.done ? "line-through text-muted-foreground" : ""}`}
                          >
                            <Streamdown>{sub.text}</Streamdown>
                          </div>
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
                          <Input
                            aria-label="Subtask text"
                            className="h-7 min-w-0 flex-1 text-xs"
                            value={subRenameText}
                            onChange={(e) => setSubRenameText(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                void renameSubtask(todo, sub.index);
                              }
                              if (e.key === "Escape") setRenamingSub(null);
                            }}
                          />
                          <Button
                            aria-label="Save subtask text"
                            size="sm"
                            variant="default"
                            onPress={() => void renameSubtask(todo, sub.index)}
                          >
                            Save
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}

                <div className="mt-1 flex gap-1">
                  <Input
                    aria-label={`New subtask for ${todo.title}`}
                    className="h-7 min-w-0 flex-1 text-xs"
                    id={`new-subtask-${todo.id}`}
                    name={`new-subtask-${todo.id}`}
                    placeholder="New subtask… (Enter to add)"
                    value={subDrafts[todo.id] ?? ""}
                    onChange={(e) =>
                      setSubDrafts((prev) => ({
                        ...prev,
                        [todo.id]: e.target.value}))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void addSubtask(todo);
                    }}
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
              </FieldSet>

              <div className="flex gap-1">
                {Object.entries(STATUS_META).map(([status, m]) => (
                  <Button
                    key={status}
                    aria-label={`Mark ${todo.title} as ${m.label}`}
                    isDisabled={busyId === todo.id}
                    size="sm"
                    variant={todo.status === status ? "default" : "secondary"}
                    onPress={() => void setStatus(todo, status)}
                  >
                    {m.icon} {m.label}
                  </Button>
                ))}
              </div>
            </div>
          );
        })}

        <div className="mt-1 flex flex-col gap-1.5 border-t border-border pt-2">
          <Input
            aria-label="New todo title"
            className="h-8 text-sm"
            id="new-todo-title"
            name="new-todo-title"
            placeholder="New todo… (Enter to add)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void createTodo();
            }}
          />
          <Textarea
            aria-label="New todo description"
            className="min-h-10 text-sm"
            id="new-todo-description"
            name="new-todo-description"
            placeholder="Description (optional)"
            rows={view === "canvas" ? 3 : 1}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <Button
            isDisabled={!title.trim() || creating}
            size="sm"
            variant="default"
            onPress={() => void createTodo()}
          >
            ＋ Add todo
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default TodoSurface;
