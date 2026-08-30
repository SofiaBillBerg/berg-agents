import React, { useEffect, useState } from "react";

export interface SubagentToolCall {
  tool?: string;
  name?: string;
  input?: any;
  output?: any;
}

export interface SubagentData {
  id?: string;
  name?: string;
  status?: "running" | "completed" | "failed" | "pending" | string;
  toolCalls?: SubagentToolCall[];
  output?: string;
}

export interface SubagentCardProps {
  subagent?: SubagentData | null;
}

const STATUS_COLORS: Record<string, string> = {
  running: "#f9a825",
  completed: "#2e7d32",
  failed: "#b00020",
  pending: "#666666",
};

const STATUS_ICONS: Record<string, string> = {
  running: "⟳",
  completed: "✓",
  failed: "✗",
  pending: "○",
};

/**
 * SubagentCard component.
 * Displays subagent execution progress, live timer, and invoked tool calls.
 *
 * @param props - Component properties
 * @returns JSX element rendering the subagent status card
 */
export function SubagentCard({ subagent }: SubagentCardProps) {
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

  const statusKey = subagent.status || "pending";
  const icon = STATUS_ICONS[statusKey] || "○";
  const color = STATUS_COLORS[statusKey] || "#666666";

  return (
    <div className="subagent-card-container mt-2 border border-border rounded-lg overflow-hidden bg-surface">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 bg-transparent border-none text-left cursor-pointer text-xs font-sans flex justify-between items-center gap-2"
      >
        <div className="flex items-center gap-2">
          <span
            style={{ color }}
            className="font-medium inline-block w-4 text-center"
          >
            {subagent.status === "running" ? (
              <span className="inline-block animate-spin">⟳</span>
            ) : (
              icon
            )}
          </span>
          <span className="font-semibold text-text">
            {subagent.name || "Subagent"}
          </span>
        </div>
        <div className="flex items-center gap-2 text-muted text-xs">
          {subagent.status === "running" && <span>{elapsed.toFixed(1)}s</span>}
          <span style={{ color }}>{subagent.status}</span>
          <span>{expanded ? "▼" : "▶"}</span>
        </div>
      </button>

      {expanded && (
        <div className="p-3 bg-bg border-t border-border text-xs text-text">
          {subagent.toolCalls && subagent.toolCalls.length > 0 ? (
            <div>
              <div className="mb-2 font-semibold">
                Tool calls ({subagent.toolCalls.length}):
              </div>
              {subagent.toolCalls.map((tc, idx) => (
                <div
                  key={`tool-call-${idx}`}
                  className="py-1 border-b border-border font-mono text-xs"
                >
                  {tc.tool || tc.name || `Tool ${idx + 1}`}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted">No tool calls recorded</div>
          )}

          {subagent.output && (
            <div className="mt-2">
              <div className="font-semibold mb-1">Output:</div>
              <div className="p-2 bg-surface rounded font-mono text-xs whitespace-pre-wrap break-all max-h-36 overflow-y-auto">
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
