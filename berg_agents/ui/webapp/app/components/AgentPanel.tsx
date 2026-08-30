import React from "react";

/**
 * AgentPanel — shows all registered agents from the orchestrator
 * with their capabilities and current status.
 */
export default function AgentPanel({agents, activeAgent, compact = false}) {
    if (!agents || agents.length === 0) {
        return <div className="agent-panel empty">No agents registered.</div>;
    }

    if (compact) {
        return (
            <div className="agent-panel compact">
                {agents.map((agent) => (
                    <span
                        key={agent.name}
                        className={`agent-chip ${activeAgent === agent.name ? "active" : ""}`}
                        title={agent.description}
                    >
                        {agent.name}
                    </span>
                ))}
            </div>
        );
    }

    return (
        <div className="agent-panel">
            <h3>Agents</h3>
            <div className="agent-list">
                {agents.map((agent) => (
                    <div
                        key={agent.name}
                        className={`agent-card ${activeAgent === agent.name ? "active" : ""}`}
                    >
                        <div className="agent-name">{agent.name}</div>
                        <div className="agent-description">{agent.description}</div>
                        <div className="agent-meta">
                            <span className="agent-tier">{agent.preferred_model_tier}</span>
                            {agent.capabilities?.map((cap) => (
                                <span key={cap} className="agent-cap">{cap}</span>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
