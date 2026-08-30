import React, { useState } from "react";

export interface TodoItem {
  status?: "pending" | "in_progress" | "completed" | string;
  content?: string;
  description?: string;
  title?: string;
}

export interface TodoListProps {
  todos?: TodoItem[];
  onTodoUpdate?: (todo: TodoItem) => void;
}

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  pending: { bg: "#e3f2fd", color: "#1565c0" },
  in_progress: { bg: "#fff3e0", color: "#e65100" },
  completed: { bg: "#e8f5e9", color: "#2e7d32" },
};

/**
 * TodoList component.
 * Renders task planning todo items with collapsible visibility and status badges.
 *
 * @param props - Component properties
 * @returns JSX element rendering the todo list section
 */
export function TodoList({ todos = [], onTodoUpdate }: TodoListProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="todo-list-container my-3 border border-border rounded-lg overflow-hidden bg-surface">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 bg-transparent border-none text-left cursor-pointer text-xs font-semibold flex justify-between items-center text-text"
      >
        <span>Todo List ({todos?.length || 0})</span>
        <span className="text-muted">{expanded ? "▼" : "▶"}</span>
      </button>

      {expanded && (
        <div className="p-2 flex flex-col gap-1.5">
          {todos && todos.length > 0 ? (
            todos.map((todo, idx) => {
              const status = todo.status || "pending";
              const style = STATUS_COLORS[status] || STATUS_COLORS.pending;
              const text =
                todo.content ||
                todo.description ||
                todo.title ||
                `Task ${idx + 1}`;

              return (
                <div
                  key={`todo-${idx}`}
                  style={{ backgroundColor: style.bg }}
                  className="p-2 rounded border border-border flex justify-between items-center text-xs text-text"
                >
                  <span className="font-medium truncate mr-2">{text}</span>
                  <span
                    style={{ backgroundColor: style.color }}
                    className="text-white text-xs px-2 py-0.5 rounded font-semibold whitespace-nowrap"
                  >
                    {status}
                  </span>
                </div>
              );
            })
          ) : (
            <div className="text-xs text-muted p-2">No todos yet</div>
          )}
        </div>
      )}
    </div>
  );
}

export default TodoList;
