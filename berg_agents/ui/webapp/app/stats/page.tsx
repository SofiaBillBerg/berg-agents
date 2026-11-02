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
 * Stats page - dedicated view for routing/outcome statistics.
 * Fetches stats from /api/router-stats on the client.
 */

"use client";

import {useEffect, useState} from "react";
import {Card, Spinner} from "@heroui/react";


import {RouterStatsPanel} from "../components/RouterStatsPanel.tsx";
import {Navbar} from "../components/Navbar.tsx";

import {API_BASE} from "@/envConfig";

/**
 * StatsPage - client component that fetches and displays router statistics.
 * Shows a spinner while loading and an empty state if no router stats exist.
 */
export default function StatsPage() {
    const [stats, setStats] = useState<unknown>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/router-stats`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                setStats(data);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Network error");
            } finally {
                setLoading(false);
            }
        };
        void fetchStats();
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
                                <span className="ml-2">Loading stats...</span>
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
                                <p className="text-sm">Failed to load stats: {error}</p>
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
                    <h1 className="text-2xl font-bold mb-4">Router Stats</h1>
                    <p className="text-sm text-muted-foreground mb-4">
                        Outcome statistics from agent runs - track success rates by task
                        type and model to understand what works best.
                    </p>
                    <RouterStatsPanel stats={stats as never}/>
                </div>
            </div>
        </>
    );
}
