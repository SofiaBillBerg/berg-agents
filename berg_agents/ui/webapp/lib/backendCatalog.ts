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
 * The backend catalog client - one reader per catalog, for the whole app.
 *
 * The app's chrome reads three catalogs from the server: plugins (five
 * places), agents (three), router stats (three). Each used to fetch the
 * endpoint itself, with its own failure handling and its own copy of the
 * response shape (the plugin descriptor alone was declared three times,
 * with three different field sets). There is now one function per
 * catalog, one type per catalog, and a small in-process cache: the
 * catalogs are static for the life of a server process, so five readers
 * cost one request, and every reader sees the same bytes.
 *
 * `invalidateCatalog()` is the one mutation hook: a plugin enabled or
 * disabled changes what the catalog reports, so the toggling surfaces
 * clear the cache and the next reader re-fetches.
 */

import type {AgentInfo} from "@/harness";

import {API_BASE} from "@/envConfig";

/** One capability descriptor from /api/plugins. */
export interface PluginCapabilityInfo {
    type: string;
    id?: string;
    name?: string;
    server_type?: string;
    enabled?: boolean;
    sensitive?: boolean;
}

/** The `ui:` block a plugin manifest declares. */
export interface PluginUiDeclaration {
    entry?: string;
    entry_url?: string;
    entry_built?: boolean;
    placement?: string;
    label?: string;
    width?: number;
}

/** One plugin as /api/plugins reports it. */
export interface PluginInfo {
    id: string;
    name: string;
    version: string;
    state: string;
    description: string;
    tools: string[];
    capabilities: PluginCapabilityInfo[];
    ui?: PluginUiDeclaration | null;
}

/** What the plugins endpoint answers. */
interface PluginsResponse {
    plugins?: PluginInfo[];
}

/**
 * The last successful answer per catalog. A failed request leaves the
 * cache alone (and returns []), so one unreachable moment never erases
 * what the chrome is already showing.
 */
const cache = new Map<string, unknown>();

/** Forget every cached catalog (after a plugin enable/disable). */
export function invalidateCatalog(): void {
    cache.clear();
}

/**
 * Fetch a catalog once, then serve it from the cache.
 *
 * @param path - Endpoint path relative to the API base.
 * @returns The payload, or null when the request failed.
 */
async function readCatalog(path: string): Promise<unknown | null> {
    if (cache.has(path)) return cache.get(path) ?? null;
    try {
        const resp = await fetch(`${API_BASE}${path}`);
        if (!resp.ok) return null;
        const data = await resp.json();
        cache.set(path, data);
        return data;
    } catch {
        // Backend unreachable: the caller keeps what it has.
        return null;
    }
}

/**
 * Read the plugin catalog.
 *
 * @returns The plugins, or [] when unavailable.
 */
export async function fetchPlugins(): Promise<PluginInfo[]> {
    const data = (await readCatalog("/api/plugins")) as PluginsResponse | null;
    return data && Array.isArray(data.plugins) ? data.plugins : [];
}

/**
 * Read the agent catalog.
 *
 * @returns The agents, or [] when unavailable.
 */
export async function fetchAgents(): Promise<AgentInfo[]> {
    const data = await readCatalog("/api/agents");
    return Array.isArray(data) ? (data as AgentInfo[]) : [];
}

/**
 * Read the router stats.
 *
 * @returns The stats payload, or null when unavailable.
 */
export async function fetchRouterStats(): Promise<unknown | null> {
    return readCatalog("/api/router-stats");
}
