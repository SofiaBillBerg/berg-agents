import React from "react";
import { Chip } from "@heroui/react";

export interface AgentInfo {
  name: string;
  description?: string;
  preferred_model_tier?: string;
  capabilities?: string[];
}

export interface AgentPanelProps {
  agents?: AgentInfo[];
  activeAgent?: string | null;
  compact?: boolean;
}

/**
 * AgentPanel component.
 * Displays all registered agents from the orchestrator with their
 * capabilities, descriptions, and current activity status.
 *
 * @param props - Component properties
 * @returns JSX element rendering the agent directory list
 */
export function AgentPanel({
  agents = [],
  activeAgent,
  compact = false,
}: AgentPanelProps) {
  if (!agents || agents.length === 0) {
    return (
      <div className="agent-panel empty text-xs text-muted p-2">
        No agents registered.
      </div>
    );
  }

  if (compact) {
    return (
      <div className="agent-panel compact flex flex-wrap gap-1.5 p-1">
        {agents.map((agent) => (
          <span
            key={agent.name}
            className={`agent-chip text-xs px-2 py-0.5 rounded ${activeAgent === agent.name ? "active bg-brand-purple text-white" : "bg-surface text-text"}`}
            title={agent.description}
          >
            {agent.name}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="agent-panel p-3 bg-surface rounded-lg border border-border">
      <h3 className="text-sm font-semibold mb-2 text-text">
        Registered Agents
      </h3>
      <div className="agent-list flex flex-col gap-2">
        {agents.map((agent) => (
          <div
            key={agent.name}
            className={`agent-card p-2 rounded border ${
              activeAgent === agent.name
                ? "active border-brand-purple bg-surface-soft"
                : "border-border bg-bg"
            }`}
          >
            <div className="agent-name font-medium text-xs text-text">
              {agent.name}
            </div>
            {agent.description && (
              <div className="agent-description text-xs text-muted mt-0.5">
                {agent.description}
              </div>
            )}
            <div className="agent-meta flex items-center gap-1.5 flex-wrap mt-1.5">
              {agent.preferred_model_tier && (
                <Chip size="sm" variant="secondary" className="text-xs">
                  {agent.preferred_model_tier}
                </Chip>
              )}
              {agent.capabilities?.map((cap) => (
                <span
                  key={cap}
                  className="agent-cap text-xs bg-surface-tint text-text px-1.5 py-0.5 rounded"
                >
                  {cap}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default AgentPanel;
