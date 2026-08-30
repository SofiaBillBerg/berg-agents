import React from "react";

/**
 * LearningPanel — shows outcome statistics from the learning gate.
 * Displays success rates per task type and model performance.
 */
export default function LearningPanel({stats, compact = false}) {
    if (!stats || stats.total === 0) {
        return (
            <div className="learning-panel empty">
                <h4>Learning Stats</h4>
                <p>No outcomes recorded yet. The learning gate will adapt as you use the agent.</p>
            </div>
        );
    }

    const byTaskType = stats.by_task_type || {};
    const byModel = stats.by_model || {};

    if (compact) {
        return (
            <div className="learning-panel compact">
                <span className="learning-stat">{stats.total} tasks</span>
                {Object.entries(byModel).map(([model, data]) => {
                    const rate = data.success + data.failure > 0
                        ? Math.round((data.success / (data.success + data.failure)) * 100)
                        : 0;
                    return (
                        <span key={model} className="learning-stat">
                            {model}: {rate}%
                        </span>
                    );
                })}
            </div>
        );
    }

    return (
        <div className="learning-panel">
            <h4>Learning Stats</h4>
            <p className="learning-summary">Total tasks: {stats.total}</p>

            {Object.keys(byTaskType).length > 0 && (
                <div className="learning-section">
                    <h5>By Task Type</h5>
                    {Object.entries(byTaskType).map(([type, data]) => {
                        const total = data.success + data.failure;
                        const rate = total > 0 ? Math.round((data.success / total) * 100) : 0;
                        return (
                            <div key={type} className="learning-row">
                                <span className="learning-label">{type}</span>
                                <div className="learning-bar">
                                    <div
                                        className="learning-bar-fill"
                                        style={{width: `${rate}%`}}
                                    />
                                </div>
                                <span className="learning-value">{rate}% ({total})</span>
                            </div>
                        );
                    })}
                </div>
            )}

            {Object.keys(byModel).length > 0 && (
                <div className="learning-section">
                    <h5>By Model</h5>
                    {Object.entries(byModel).map(([model, data]) => {
                        const total = data.success + data.failure;
                        const rate = total > 0 ? Math.round((data.success / total) * 100) : 0;
                        return (
                            <div key={model} className="learning-row">
                                <span className="learning-label">{model}</span>
                                <div className="learning-bar">
                                    <div
                                        className="learning-bar-fill"
                                        style={{width: `${rate}%`}}
                                    />
                                </div>
                                <span className="learning-value">{rate}% ({total})</span>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
