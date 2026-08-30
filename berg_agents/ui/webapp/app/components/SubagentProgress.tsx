import React from 'react';

/**
 * SubagentProgress component
 * @param {{ subagents: Array<{id: string, name: string, status: string}> }} props
 */
function SubagentProgress({subagents}) {
    const completed = subagents.filter(sa => sa.status === 'complete').length;
    const total = subagents.length;
    const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

    if (total === 0) return null;

    return (
        <div className="subagent-progress" style={{marginTop: "var(--berg-sp-4)", marginBottom: "var(--berg-sp-4)"}}>
            <div style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontSize: "var(--berg-fs-sm)",
                color: "var(--berg-muted)",
                marginBottom: "var(--berg-sp-2)"
            }}>
                <span>Subagent Progress</span>
                <span>{completed} / {total} complete</span>
            </div>
            <div style={{
                height: "6px",
                background: "var(--berg-border)",
                borderRadius: "var(--berg-radius-lg)",
                overflow: "hidden"
            }}>
                <div
                    style={{
                        height: "100%",
                        background: "var(--berg-gradient-brand)",
                        borderRadius: "var(--berg-radius-lg)",
                        transition: "width 0.3s ease",
                        width: `${percentage}%`
                    }}
                />
            </div>
        </div>
    );
}

export default SubagentProgress;
