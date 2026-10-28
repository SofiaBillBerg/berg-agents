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

import type {AgentInfo} from "@/harness/webhook";

import {useEffect, useState} from "react";
import {Card, Spinner} from "@heroui/react";

import {API_BASE} from "@/envConfig";

import {AgentPanel} from "../components/AgentPanel.tsx";
import {Navbar} from "../components/Navbar.tsx";

/** localStorage key for the selected (active) agent — behavior TBD. */
const SELECTED_AGENT_KEY = "berg-selected-agent";

/**
 * AgentsPage - client component that fetches and displays all registered
 * agents. Shows a spinner while loading and an empty state if no agents.
 */
export default function AgentsPage() {
    const [agents, setAgents] = useState<AgentInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // The backend (/api/agents/active) is the source of truth for the
    // active agent; localStorage is only a cache for offline display.
    const [activeAgent, setActiveAgent] = useState<string | null>(null);

    // Sync from the backend on mount so the Agents page and the header
    // AgentSelector agree (and survive reloads without drift).
    useEffect(() => {
        let cancelled = false;
        void fetch(`${API_BASE}/api/agents/active`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (cancelled) return;
                const agent =
                    data && typeof data.agent === "string" ? data.agent : null;
                setActiveAgent(agent);
                try {
                    if (agent) localStorage.setItem(SELECTED_AGENT_KEY, agent);
                    else localStorage.removeItem(SELECTED_AGENT_KEY);
                } catch {
                    // Private-mode storage: selection stays in memory only.
                }
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, []);

    // Click the active agent again to clear the selection. Backend is
    // the source of truth; we update local state from its response so
    // the UI never drifts from what the server actually stored.
    const selectAgent = (name: string) => {
        const next = activeAgent === name ? null : name;
        setActiveAgent(next);
        try {
            if (next) localStorage.setItem(SELECTED_AGENT_KEY, next);
            else localStorage.removeItem(SELECTED_AGENT_KEY);
        } catch {
            // Private-mode storage: selection stays in memory only.
        }
        void fetch(`${API_BASE}/api/agents/active`, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({agent: next})})
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data && typeof data.agent === "string") {
                    setActiveAgent(data.agent);
                } else if (data && data.agent === null) {
                    setActiveAgent(null);
                }
            })
            .catch(() => undefined);
    };

    useEffect(() => {
        const fetchAgents = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/agents`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                setAgents(data || []);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Network error");
            } finally {
                setLoading(false);
            }
        };
        void fetchAgents();
    }, []);

    if (loading) {
        return (
            <>
                <Navbar/>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto w-full max-w-6xl p-4">
                        <Card variant="default">
                            <Card.Content className="flex items-center justify-center py-8">
                                <Spinner size="lg"/>
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
                <Navbar/>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    <div className="mx-auto w-full max-w-6xl p-4">
                        <Card className="border border-danger" variant="default">
                            <Card.Header>
                                <Card.Title className="text-danger">Error</Card.Title>
                            </Card.Header>
                            <Card.Content>
                                <p className="text-sm">Failed to load agents: {error}</p>
                            </Card.Content>
                        </Card>
                    </div>
                </div>
            </>
        );
    }

    return (
        <>
            <Navbar/>
            {/* Scroll region: the app shell (body > #root) never scrolls
          itself, so each page owns exactly one vertical scroll
          container that fills the space below the navbar. */}
            <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-6xl p-4">
                    <h1 className="text-2xl font-bold mb-4">Registered Agents</h1>
                    <p className="text-sm text-muted-foreground mb-4">
                        {agents.length} agent(s) available - each handles different task
                        types via the BergAgents harness pipeline.{" "}
                        {activeAgent
                            ? `Active: ${activeAgent} (next chat turn routes to it).`
                            : "Click an agent to select it."}
                    </p>
                    <AgentPanel
                        activeAgent={activeAgent}
                        agents={agents}
                        onSelect={selectAgent}
                    />
                </div>
            </div>
        </>
    );
}
