import { Avatar, Card, Chip } from "@heroui/react";

export interface AgentInfo {
  name: string;
  description?: string;
  preferred_complexity?: string;
  capabilities?: string[];
}

export interface AgentPanelProps {
  agents?: AgentInfo[];
  activeAgent?: string | null;
  compact?: boolean;
}

/**
 * AgentPanel component.
 * Displays all registered agents from the harness with their
 * capabilities, descriptions, and current activity status.
 *
 * @param props - Component properties
 * @returns JSX element rendering the agent directory list
 */
export function AgentPanel({
  agents = [],
  activeAgent,
  compact = false}: AgentPanelProps) {
  if (!agents || agents.length === 0) {
    return (
      <section aria-label="Registered agents" className="agent-panel empty">
        <Card>
          <Card.Content>
            <Card.Description>No agents registered.</Card.Description>
          </Card.Content>
        </Card>
      </section>
    );
  }

  if (compact) {
    return (
      <div
        aria-label="Registered agents"
        className="agent-panel compact flex min-h-11 flex-wrap items-center gap-1.5 p-1"
      >
        {agents.map((agent) => (
          <div key={agent.name} className="flex items-center gap-1.5">
            <Avatar
              color={activeAgent === agent.name ? "success" : "default"}
              size="sm"
            >
              {agent.name?.substring(0, 2).toUpperCase() || "??"}
            </Avatar>
            {activeAgent === agent.name ? (
              <Chip color="accent" size="sm" variant="soft">
                {agent.name}
              </Chip>
            ) : (
              <Chip size="sm" variant="secondary">
                {agent.name}
              </Chip>
            )}
          </div>
        ))}
      </div>
    );
  }

  return (
    <section aria-label="Registered agents" className="agent-panel">
      <Card>
        <Card.Header>
          <Card.Title>Registered Agents</Card.Title>
          <Card.Description>
            {agents.length} available
            {activeAgent ? ` . ${activeAgent} active` : ""}
          </Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-2">
          {agents.map((agent) => {
            const isActive = activeAgent === agent.name;
            return (
              <Card
                key={agent.name}
                variant={isActive ? "secondary" : "transparent"}
              >
                <Card.Header className="flex items-start gap-3">
                  <Avatar
                    className="mt-0.5"
                    color={isActive ? "success" : "accent"}
                    size="md"
                  >
                    {agent.name?.substring(0, 2).toUpperCase() || "??"}
                  </Avatar>
                  <div className="flex-1">
                    <Card.Title>{agent.name}</Card.Title>
                    {agent.description && (
                      <Card.Description>{agent.description}</Card.Description>
                    )}
                  </div>
                  {isActive && (
                    <Chip color="success" size="sm" variant="soft">
                      Active
                    </Chip>
                  )}
                </Card.Header>
                <Card.Content className="flex flex-wrap items-center gap-1.5">
                  {isActive && (
                    <Chip color="success" size="sm" variant="primary">
                      Active
                    </Chip>
                  )}
                  {agent.preferred_complexity && (
                    <Chip size="sm" variant="secondary">
                      {agent.preferred_complexity}
                    </Chip>
                  )}
                  {agent.capabilities?.map((cap) => (
                    <Chip key={cap} size="sm" variant="soft">
                      {cap}
                    </Chip>
                  ))}
                </Card.Content>
              </Card>
            );
          })}
        </Card.Content>
      </Card>
    </section>
  );
}

export default AgentPanel;
