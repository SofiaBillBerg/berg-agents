import React from "react";

/**
 * SubtaskPanel — shows planner subtasks with their status,
 * complexity, and model tier assignments.
 */
export default function SubtaskPanel({subtasks, isPlanning = false}) {
    if (!subtasks || subtasks.length === 0) {
        if (isPlanning) {
            return (
                <div className="subtask-panel planning">
                    <span className="spinner">⟳</span> Planning task decomposition…
                </div>
            );
        }
        return null;
    }

    const complexityColors = {
        trivial: "#4caf50",
        standard: "#ff9800",
        complex: "#f44336",
        critical: "#9c27b0",
    };

    return (
        <div className="subtask-panel">
            <h4>Execution Plan ({subtasks.length} steps)</h4>
            <div className="subtask-list">
                {subtasks.map((task, idx) => (
                    <div key={task.id || idx} className="subtask-item">
                        <span className="subtask-num">{idx + 1}</span>
                        <div className="subtask-info">
                            <div className="subtask-desc">{task.description}</div>
                            <div className="subtask-meta">
                                <span
                                    className="subtask-complexity"
                                    style={{color: complexityColors[task.complexity] || "#999"}}
                                >
                                    {task.complexity}
                                </span>
                                <span className="subtask-tier">{task.estimated_model_tier}</span>
                                {task.dependencies?.length > 0 && (
                                    <span className="subtask-deps">
                                        ↳ depends on {task.dependencies.join(", ")}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
