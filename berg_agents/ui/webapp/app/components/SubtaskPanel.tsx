import React from "react";

export interface SubtaskItem {
  id?: string;
  description?: string;
  complexity?: "trivial" | "standard" | "complex" | "critical" | string;
  estimated_model_tier?: string;
  dependencies?: string[];
}

export interface SubtaskPanelProps {
  subtasks?: SubtaskItem[];
  isPlanning?: boolean;
}

const COMPLEXITY_COLORS: Record<string, string> = {
  trivial: "#4caf50",
  standard: "#ff9800",
  complex: "#f44336",
  critical: "#9c27b0",
};

/**
 * SubtaskPanel component.
 * Displays planner execution subtasks, complexity tiers, and dependency ordering.
 *
 * @param props - Component properties
 * @returns JSX element rendering the subtasks panel
 */
export function SubtaskPanel({
  subtasks = [],
  isPlanning = false,
}: SubtaskPanelProps) {
  if (!subtasks || subtasks.length === 0) {
    if (isPlanning) {
      return (
        <div className="subtask-panel planning p-3 text-xs text-brand-purple flex items-center gap-2">
          <span className="spinner">⟳</span> Planning task decomposition…
        </div>
      );
    }
    return null;
  }

  return (
    <div className="subtask-panel p-3 bg-surface rounded-lg border border-border">
      <h4 className="font-semibold text-sm mb-2 text-text">
        Execution Plan ({subtasks.length} steps)
      </h4>
      <div className="subtask-list flex flex-col gap-2">
        {subtasks.map((task, idx) => {
          const compKey = task.complexity
            ? String(task.complexity).toLowerCase()
            : "";
          const color = COMPLEXITY_COLORS[compKey] || "#888";
          return (
            <div
              key={task.id || `subtask-${idx}`}
              className="subtask-item flex items-start gap-2.5 p-2 bg-bg rounded border border-border text-xs"
            >
              <span className="subtask-num font-mono font-bold text-muted w-5 text-center">
                {idx + 1}
              </span>
              <div className="subtask-info flex-1">
                <div className="subtask-desc font-medium text-text">
                  {task.description}
                </div>
                <div className="subtask-meta flex items-center gap-2 flex-wrap mt-1">
                  {task.complexity && (
                    <span
                      className="subtask-complexity font-semibold"
                      style={{ color }}
                    >
                      {task.complexity}
                    </span>
                  )}
                  {task.estimated_model_tier && (
                    <span className="subtask-tier bg-surface-tint px-1.5 py-0.5 rounded text-muted">
                      {task.estimated_model_tier}
                    </span>
                  )}
                  {task.dependencies && task.dependencies.length > 0 && (
                    <span className="subtask-deps text-muted">
                      ↳ depends on {task.dependencies.join(", ")}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SubtaskPanel;
