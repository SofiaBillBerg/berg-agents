/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

/* AgentSelector - pick the active agent for the chat session.
 *
 * Mirrors ProviderSelector: reads the agent list + the active selection,
 * and PUTs the choice to /api/agents/active so the next chat turn routes
 * to that agent (the chat agent adopts its persona). The selection is
 * also persisted on the backend session, so the Agents page and the
 * header agree.
 *
 * Both reads are the same SWR keys the Agents page uses, so the header
 * and that page share one cache rather than each fetching their own copy
 * and occasionally disagreeing about which agent is active.
 */

"use client";

import type { AgentInfo } from "@/harness";

import { useEffect } from "react";
import useSWR from "swr";

import {
  ACTIVE_AGENT_KEY,
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchActiveAgent,
  fetchAgents,
  storeActiveAgent} from "@/lib/backendCatalog";

/** AgentSelector - header control for the active agent. */
export default function AgentSelector() {
  // One reader per catalog — the shared keys, so a change made on the
  // Agents page shows up here without a reload.
  const { data: agents = [] } = useSWR<AgentInfo[]>(
    CATALOG_KEYS.agents,
    fetchAgents,
    CATALOG_SWR_OPTIONS,
  );
  const { data: activePayload, mutate: mutateActive } = useSWR(
    ACTIVE_AGENT_KEY,
    fetchActiveAgent,
  );
  const active = activePayload?.agent ?? null;

  // Mirror the server's answer into localStorage for offline display.
  // Writing an external store rather than state, so an Effect is the
  // right home for it.
  useEffect(() => {
    if (activePayload === undefined) return;
    storeActiveAgent(activePayload.agent);
  }, [activePayload]);

  /**
   * Set the active agent on the backend (and locally).
   *
   * @param name - The chosen agent, or "" to fall back to the default.
   */
  const onChange = (name: string) => {
    const next = name === "" ? null : name;
    storeActiveAgent(next);
    // Optimistic: show the choice at once, then confirm it against the
    // server. `revalidate: false` keeps the PUT's own answer as the
    // final word instead of immediately re-fetching over it.
    void mutateActive(
      async () => {
        const resp = await fetch(ACTIVE_AGENT_KEY, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent: next })});
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return (await resp.json()) as { agent: string | null };
      },
      {
        optimisticData: { agent: next },
        revalidate: false},
    ).catch(() => undefined);
  };

  return (
    <select
      aria-label="Active agent"
      className="rounded-md border border-border bg-background px-2 py-1 text-sm"
      id="active-agent"
      name="active-agent"
      title={
        active
          ? `Active agent: ${active} - next message routes to it`
          : "Default chat agent"
      }
      value={active ?? ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Default chat agent</option>
      {agents.map((a) => (
        <option key={a.name} value={a.name}>
          {a.name}
        </option>
      ))}
    </select>
  );
}
