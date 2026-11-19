/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

import { Avatar, Card, Chip } from "@heroui/react";

import { Badge } from "@/components/ui/badge.tsx";

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
  /** Make each agent selectable; called with the clicked agent's name.
     Omit to keep the panel read-only (display only). */
  onSelect?: (name: string) => void;
}

/**
 * AgentPanel component.
 * Displays all registered agents from the harness with their
 * capabilities, descriptions, and current activity status. When
 * `onSelect` is provided each agent is a button with a clear active
 * state; without it the panel stays read-only.
 *
 * @param props - Component properties
 * @returns JSX element rendering the agent directory list
 */
export function AgentPanel({
  agents = [],
  activeAgent,
  compact = false,
  onSelect}: AgentPanelProps) {
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
        {agents.map((agent) => {
          const isActive = activeAgent === agent.name;
          const row = (
            <div className="flex items-center gap-1.5">
              <Avatar color={isActive ? "success" : "default"} size="sm">
                {agent.name?.substring(0, 2).toUpperCase() || "??"}
              </Avatar>
              {isActive ? (
                <Chip color="accent" size="sm" variant="soft">
                  {agent.name}
                </Chip>
              ) : (
                <Chip size="sm" variant="secondary">
                  {agent.name}
                </Chip>
              )}
            </div>
          );
          // Read-only when no handler; otherwise a clear pressable chip.
          if (!onSelect) {
            return <div key={agent.name}>{row}</div>;
          }
          return (
            <button
              key={agent.name}
              aria-pressed={isActive}
              className={`cursor-pointer rounded-full transition hover:opacity-90 ${
                isActive ? "ring-2 ring-success" : ""
              }`}
              type="button"
              onClick={() => onSelect(agent.name)}
            >
              {row}
            </button>
          );
        })}
      </div>
    );
  }

  // Full view: a LIST, not a grid of cards. Five rows do not need a
  // card each — that was five boxes around a name and some text, which
  // made the page about its own chrome. The row keeps everything the
  // cards had (initials, name, description, complexity, capabilities,
  // active state) at a fraction of the height, and selects the same way.
  const row = (agent: AgentInfo) => {
    const isActive = activeAgent === agent.name;
    const content = (
      <>
        <Avatar
          className="size-6 text-[10px]"
          color={isActive ? "success" : "accent"}
        >
          {agent.name?.substring(0, 2).toUpperCase() || "??"}
        </Avatar>
        <span className="font-medium">{agent.name}</span>
        {isActive && <Badge variant="secondary">Active</Badge>}
        <span className="min-w-0 flex-1 truncate opacity-70">
          {agent.description}
        </span>
        {agent.preferred_complexity && (
          <Badge variant="outline">{agent.preferred_complexity}</Badge>
        )}
        {agent.capabilities?.map((cap) => (
          <Badge key={cap} variant="outline">
            {cap}
          </Badge>
        ))}
      </>
    );
    if (!onSelect) {
      return (
        <div key={agent.name} className="flex items-center gap-2 px-1 py-1">
          {content}
        </div>
      );
    }
    return (
      <button
        key={agent.name}
        aria-pressed={isActive}
        className={`flex w-full items-center gap-2 rounded px-1 py-1 text-left text-xs transition hover:bg-muted ${
          isActive ? "bg-muted" : ""
        }`}
        type="button"
        onClick={() => onSelect(agent.name)}
      >
        {content}
      </button>
    );
  };

  return (
    <section aria-label="Registered agents" className="agent-panel">
      <div className="flex flex-col">{agents.map(row)}</div>
    </section>
  );
}

export default AgentPanel;
