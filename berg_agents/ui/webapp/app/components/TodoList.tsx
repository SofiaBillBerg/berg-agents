import React, {useState} from "react";

/**
 * TodoList component
 * Renders todos SSE events with status badges (pending/in_progress/completed)
 * Collapsible panel
 */
function TodoList({todos, onTodoUpdate}) {
    const [expanded, setExpanded] = useState(true);

    // Status badge colors
    const statusColors = {
        pending: {bg: "#e3f2fd", color: "#1565c0"},
        in_progress: {bg: "#fff3e0", color: "#e65100"},
        completed: {bg: "#e8f5e9", color: "#2e7d32"},
    };

    const getStatusStyle = (status) => {
        return statusColors[status] || statusColors.pending;
    };

    return (
        <div
            style={{
                marginTop: "0.75rem",
                border: "1px solid #e0e0e0",
                borderRadius: "6px",
                overflow: "hidden",
            }}
        >
            <button
                onClick={() => setExpanded(!expanded)}
                style={{
                    width: "100%",
                    padding: "0.5rem 0.75rem",
                    background: "transparent",
                    border: "none",
                    textAlign: "left",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    fontFamily: "inherit",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                }}
            >
        <span style={{fontWeight: "500", color: "#333"}}>
          Todo List ({todos?.length || 0})
        </span>
                <span style={{color: "#666"}}>
          {expanded ? "▼" : "▶"}
        </span>
            </button>
            {expanded && (
                <div style={{padding: "0.5rem"}}>
                    {todos && todos.length > 0 ? (
                        todos.map((todo, idx) => {
                            const style = getStatusStyle(todo.status);
                            return (
                                <div
                                    key={idx}
                                    style={{
                                        padding: "0.5rem",
                                        marginBottom: "0.25rem",
                                        background: style.bg,
                                        border: "1px solid #e0e0e0",
                                        borderRadius: "4px",
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                    }}
                                >
                  <span style={{fontSize: "0.85rem", color: "#333"}}>
                    {/* DeepAgents write_todos items use `content` (not
                        description/title) - without this check every task
                        rendered as a generic "Task N" placeholder. */}
                      {todo.content || todo.description || todo.title || `Task ${idx + 1}`}
                  </span>
                                    <span
                                        style={{
                                            fontSize: "0.75rem",
                                            padding: "0.2rem 0.5rem",
                                            borderRadius: "4px",
                                            background: style.color,
                                            color: "#fff",
                                            fontWeight: "500",
                                        }}
                                    >
                    {todo.status || "pending"}
                  </span>
                                </div>
                            );
                        })
                    ) : (
                        <div style={{fontSize: "0.8rem", color: "#999", padding: "0.5rem"}}>
                            No todos yet
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default TodoList;
