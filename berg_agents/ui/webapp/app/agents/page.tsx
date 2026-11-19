/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
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
 * Agents page - dedicated view for registered agents and their details.
 * Fetches agent list from /api/agents on the client.
 */

"use client";

import type { AgentInfo } from "@/harness/webhook";

import { useEffect } from "react";
import { Card, Spinner } from "@heroui/react";
import useSWR from "swr";

import { AgentPanel } from "../components/AgentPanel.tsx";
import { Navbar } from "../components/Navbar.tsx";

import {
  ACTIVE_AGENT_KEY,
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchActiveAgent,
  fetchAgents,
  storeActiveAgent,
  type ActiveResponse} from "@/lib/backendCatalog";

/**
 * AgentsPage - client component that displays all registered agents.
 * Shows a spinner while loading and an empty state if no agents.
 */
export default function AgentsPage() {
  // The backend (/api/agents/active) is the source of truth for the
  // active agent; localStorage is only a cache for offline display.
  // Derived straight from the SWR cache so the panel and the header
  // AgentSelector can never disagree — they read the same key.
  const { data: activePayload, mutate: mutateActive } = useSWR<ActiveResponse>(
    ACTIVE_AGENT_KEY,
    fetchActiveAgent,
  );
  const activeAgent = activePayload?.agent ?? null;

  const {
    data: agents,
    error,
    isLoading} = useSWR<AgentInfo[]>(
    CATALOG_KEYS.agents,
    fetchAgents,
    CATALOG_SWR_OPTIONS,
  );

  // Keep the offline cache in step with the server's answer, on arrival
  // and after every revalidation, so a change made in another window
  // converges here too. This writes localStorage rather than state, which
  // is why it is an Effect and not a derivation.
  useEffect(() => {
    if (activePayload === undefined) return;
    storeActiveAgent(activePayload.agent);
  }, [activePayload]);

  // Click the active agent again to clear the selection. Backend is
  // the source of truth; the cache is written optimistically and then
  // confirmed by the PUT, so the UI never drifts from what the server
  // actually stored.
  const selectAgent = (name: string) => {
    const next = activeAgent === name ? null : name;
    storeActiveAgent(next);
    void mutateActive(
      async () => {
        const resp = await fetch(ACTIVE_AGENT_KEY, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent: next })});
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return (await resp.json()) as ActiveResponse;
      },
      {
        optimisticData: { agent: next },
        revalidate: false},
    ).catch(() => undefined);
  };

  if (isLoading) {
    return (
      <>
        <Navbar />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4">
            <Card variant="default">
              <Card.Content className="flex items-center justify-center py-8">
                <Spinner size="lg" />
                <span className="ml-2">Loading agents...</span>
              </Card.Content>
            </Card>
          </div>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <Navbar />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4">
            <Card className="border border-danger" variant="default">
              <Card.Header>
                <Card.Title className="text-danger">Error</Card.Title>
              </Card.Header>
              <Card.Content>
                <p className="text-sm">
                  Failed to load agents: {error.message}
                </p>
              </Card.Content>
            </Card>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      {/* Scroll region: the app shell (body > #root) never scrolls
          itself, so each page owns exactly one vertical scroll
          container that fills the space below the navbar. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="text-2xl font-bold mb-2">Agents</h1>
          {/* What this page is for, said plainly: five initials and some
                task-type chips told a reader nothing about what an agent
                IS. An agent is a specialist brain the chat can hand a
                task to — the orchestrator delegates to them, and choosing
                one here routes the next chat turn to it. */}
          <p className="text-sm text-muted-foreground mb-4">
            An agent is a specialist brain in berg's harness. When you chat, the
            general agent does the work itself; choosing one here hands the next
            turn to that specialist instead — the orchestrator delegates to the
            same ones when a task needs their skills.{" "}
            {activeAgent
              ? `Active: ${activeAgent} (next chat turn routes to it).`
              : "None active — the general agent answers. Click one to select it."}
          </p>
          <AgentPanel
            activeAgent={activeAgent}
            agents={agents ?? []}
            onSelect={selectAgent}
          />
        </div>
      </div>
    </>
  );
}
