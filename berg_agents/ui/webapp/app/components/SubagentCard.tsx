import React, {useEffect, useState} from "react";

/**
 * SubagentCard component
 * Displays subagent card with name, status, and tool call info
 * Shows spinner while running, elapsed time, and tool call count
 * Collapsible and compact
 */
function SubagentCard({subagent}) {
    const [expanded, setExpanded] = useState(false);
    const [elapsed, setElapsed] = useState(0);

    // Track elapsed time while subagent is running
    useEffect(() => {
        if (subagent?.status === "running") {
            const startTime = Date.now();
            const interval = setInterval(() => {
                setElapsed((Date.now() - startTime) / 1000);
            }, 1000);
            return () => clearInterval(interval);
        }
    }, [subagent?.status]);

    if (!subagent) return null;

    const statusIcons = {
        running: "⟳",
        completed: "✓",
        failed: "✗",
        pending: "○",
    };

    const statusColors = {
        running: "#f9a825",
        completed: "#2e7d32",
        failed: "#b00020",
        pending: "#666",
    };

    const icon = statusIcons[subagent.status] || "○";
    const color = statusColors[subagent.status] || "#666";

    return (
        <div
            style={{
                marginTop: "0.5rem",
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
                    gap: "0.5rem",
                }}
            >
                <div style={{display: "flex", alignItems: "center", gap: "0.5rem"}}>
          <span
              style={{
                  color: color,
                  fontWeight: "500",
                  display: "inline-block",
                  width: "1.2em",
                  textAlign: "center",
              }}
          >
            {subagent.status === "running" && (
                <span
                    style={{
                        animation: "spin 1s linear infinite",
                        display: "inline-block",
                    }}
                >
                ⟳
              </span>
            )}
              {subagent.status !== "running" && icon}
          </span>
                    <span>{subagent.name || "Subagent"}</span>
                </div>
                <div
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.5rem",
                        color: "#666",
                        fontSize: "0.8rem",
                    }}
                >
                    {subagent.status === "running" && (
                        <span>{elapsed.toFixed(1)}s</span>
                    )}
                    <span style={{color: color}}>{subagent.status}</span>
                    <span>{expanded ? "▼" : "▶"}</span>
                </div>
            </button>
            {expanded && (
                <div
                    style={{
                        padding: "0.75rem",
                        background: "#fafafa",
                        borderTop: "1px solid #e0e0e0",
                        fontSize: "0.8rem",
                        color: "#666",
                    }}
                >
                    {subagent.toolCalls && subagent.toolCalls.length > 0 ? (
                        <div>
                            <div style={{marginBottom: "0.5rem", fontWeight: "500"}}>
                                Tool calls ({subagent.toolCalls.length}):
                            </div>
                            {subagent.toolCalls.map((tc, idx) => (
                                <div
                                    key={idx}
                                    style={{
                                        padding: "0.25rem 0",
                                        borderBottom: "1px solid #eee",
                                        fontFamily: "monospace",
                                    }}
                                >
                                    {tc.tool || tc.name || `Tool ${idx + 1}`}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div>No tool calls recorded</div>
                    )}
                    {subagent.output && (
                        <div style={{marginTop: "0.5rem"}}>
                            <div style={{fontWeight: "500", marginBottom: "0.25rem"}}>
                                Output:
                            </div>
                            <div
                                style={{
                                    padding: "0.5rem",
                                    background: "#f5f5f5",
                                    borderRadius: "4px",
                                    fontFamily: "monospace",
                                    fontSize: "0.75rem",
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                    maxHeight: "150px",
                                    overflowY: "auto",
                                }}
                            >
                                {subagent.output}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default SubagentCard;
