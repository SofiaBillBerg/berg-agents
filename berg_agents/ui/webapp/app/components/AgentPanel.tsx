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
 * along with this program.  If not, see <https://gnu.org>.
 */

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription } from "@/components/ui/card";

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
          <CardContent className="pt-4">
            <CardDescription>No agents registered.</CardDescription>
          </CardContent>
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
          const initials = agent.name?.substring(0, 2).toUpperCase() || "??";
          const row = (
            <div className="flex items-center gap-1.5">
              <Avatar className="size-6 text-[10px]">
                <AvatarFallback
                  className={
                    isActive
                      ? "bg-emerald-600 text-white"
                      : "bg-muted text-muted-foreground"
                  }
                >
                  {initials}
                </AvatarFallback>
              </Avatar>
              <Badge variant={isActive ? "default" : "secondary"}>
                {agent.name}
              </Badge>
            </div>
          );

          if (!onSelect) {
            return <div key={agent.name}>{row}</div>;
          }
          return (
            <button
              key={agent.name}
              aria-pressed={isActive}
              className={`cursor-pointer rounded-full transition hover:opacity-90 ${
                isActive ? "ring-2 ring-emerald-600" : ""
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

  const row = (agent: AgentInfo) => {
    const isActive = activeAgent === agent.name;
    const initials = agent.name?.substring(0, 2).toUpperCase() || "??";
    const content = (
      <>
        <Avatar className="size-6 text-[10px]">
          <AvatarFallback
            className={
              isActive
                ? "bg-emerald-600 text-white"
                : "bg-primary/15 text-primary"
            }
          >
            {initials}
          </AvatarFallback>
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
