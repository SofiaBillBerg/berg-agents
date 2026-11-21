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
 * along with this program.  If not, see <https://gnu.org>.
 */

/*
 * Agents page - dedicated view for registered agents and their details.
 * Fetches agent list from /api/agents on the client.
 */

"use client";

import type { AgentInfo } from "@/harness/webhook";

import { useEffect } from "react";
import useSWR from "swr";

import { AgentPanel } from "../components/AgentPanel.tsx";
import { Navbar } from "../components/Navbar.tsx";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
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

  useEffect(() => {
    if (activePayload === undefined) return;
    storeActiveAgent(activePayload.agent);
  }, [activePayload]);

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
            <Card>
              <CardContent className="flex items-center justify-center py-8">
                <Spinner className="size-6" />
                <span className="ml-2">Loading agents...</span>
              </CardContent>
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
            <Card className="border-destructive">
              <CardHeader>
                <CardTitle className="text-destructive">Error</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">
                  Failed to load agents: {error.message}
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="mb-2 text-2xl font-bold">Agents</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            An agent is a specialist brain in berg&apos;s harness. When you
            chat, the general agent does the work itself; choosing one here
            hands the next turn to that specialist instead — the orchestrator
            delegates to the same ones when a task needs their skills.{" "}
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
