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

/*
 * The backend catalog - everything the app knows about the server.
 *
 * The host reads three catalogs to draw its chrome: the tool list (the
 * slash palette and tool execution), the agent list (the selector), and
 * the router stats (the stats panel). They were three copies of the same
 * fetch-then-set pattern, each with its own failure handling and its own
 * shape; there is now one reader per catalog behind a single hook, and
 * a failure in one leaves the other two intact rather than taking the
 * chrome down with it.
 */

import {useEffect, useState} from "react";

/** What the hook needs. */
export interface UseBackendCatalogDeps {
    /** Base URL of the Berg Agents API. */
    apiBase: string;
}

/** The three catalogs, each independently loadable. */
export interface BackendCatalog {
    /** Workspace file tools, run_task, and the delegated plan/implement
        entries, each with a one-line description. */
    backendTools: Array<{name: string; description: string; source: string}>;
    /** The agent list for the selector. */
    agents: Array<{
        name: string;
        description?: string;
        preferred_complexity?: string;
        capabilities?: string[];
    }>;
    /** Router stats for the stats panel, or null before they arrive. */
    routerStats: unknown;
}

/**
 * Read the backend's three catalogs, once each, on mount.
 *
 * @param deps - The API base.
 * @returns The three catalogs (each empty or null until it loads).
 */
export function useBackendCatalog(
    deps: UseBackendCatalogDeps,
): BackendCatalog {
    const {apiBase} = deps;

    // Backend tool catalog (powers the slash palette + execution).
    // Fetched once, before the palette below reads it: workspace file
    // tools, run_task, and the delegated plan/implement entries, each
    // with a one-line description.
    const [backendTools, setBackendTools] = useState<
        Array<{name: string; description: string; source: string}>
    >([]);
    useEffect(() => {
        fetch(`${apiBase}/api/tools`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (data && Array.isArray(data.tools)) setBackendTools(data.tools);
            })
            .catch(() => setBackendTools([]));
    }, [apiBase]);

    // Local agent list (fetched from /api/agents)
    const [agents, setAgents] = useState<
        Array<{
            name: string;
            description?: string;
            preferred_complexity?: string;
            capabilities?: string[];
        }>
    >([]);
    useEffect(() => {
        fetch(`${apiBase}/api/agents`)
            .then((r) => (r.ok ? r.json() : []))
            .then((data) => setAgents(data || []))
            .catch(() => setAgents([]));
    }, [apiBase]);

    // Fetch Router stats on mount
    const [routerStats, setRouterStats] = useState<unknown>(null);
    useEffect(() => {
        fetch(`${apiBase}/api/router-stats`)
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => setRouterStats(data))
            .catch(() => {});
    }, [apiBase]);

    return {backendTools, agents, routerStats};
}
