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
 * The backend catalog client - one fetcher per catalog, for the whole app.
 *
 * The app's chrome reads four catalogs from the server: plugins, agents,
 * router stats and the tool list. Each used to fetch the endpoint itself,
 * with its own failure handling and its own copy of the response shape
 * (the plugin descriptor alone was declared three times, with three
 * different field sets). There is now one fetcher per catalog and one
 * type per catalog, keyed by CATALOG_KEYS so every reader shares SWR's
 * cache: five readers of the plugins endpoint cost one request, and every
 * reader sees the same bytes.
 *
 * The fetchers THROW on a failed request instead of answering `[]` or
 * `null`. That distinction is the whole point: SWR keeps the last good
 * `data` and records the failure in `error`, so one unreachable moment
 * never erases what the chrome is already showing. Returning a falsy
 * fallback made every caller's success path indistinguishable from its
 * failure path, and they all applied the fallback as if it were real —
 * clearing the plugin list whenever the backend was merely down.
 *
 * `invalidateCatalog()` is the one mutation hook: a plugin enabled or
 * disabled changes what the catalog reports, so the toggling surfaces
 * revalidate the keys and every reader refetches together.
 */

import type { AgentInfo } from "@/harness";

import { mutate } from "swr";

import { API_BASE } from "@/envConfig";

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
 * The SWR key for every catalog, so a reader (`useSWR`) and a mutation
 * (`mutate`) name the same entry. Derived from API_BASE rather than
 * spelled out, because callers pass `apiBase` around and a mismatched
 * key would silently split one catalog into two caches.
 */
export const CATALOG_KEYS = {
  plugins: `${API_BASE}/api/plugins`,
  agents: `${API_BASE}/api/agents`,
  routerStats: `${API_BASE}/api/router-stats`,
  tools: `${API_BASE}/api/tools`} as const;

/**
 * How often a catalog is re-read on its own, in ms.
 *
 * A catalog is not only changed through the UI: a plugin file is edited
 * on disk, an agent's definition is saved, a new tool registers. Nothing
 * posts an event when that happens, so without a poll the browser keeps
 * serving the list it read at mount until someone reloads. Polling is
 * what closes that gap — the endpoints are cheap, local reads.
 */
export const CATALOG_REFRESH_MS = 15_000;

/**
 * Shared SWR options for every catalog reader: re-poll on the interval,
 * and keep the last good list visible while a re-poll fails (the fetchers
 * throw, so SWR records the error without dropping `data`). Pass this as
 * the third `useSWR` argument so the cadence lives in one place instead
 * of being restated — and drift — at each call site.
 */
export const CATALOG_SWR_OPTIONS = {
  refreshInterval: CATALOG_REFRESH_MS,
  keepPreviousData: true} as const;

/**
 * Revalidate every catalog. Used after a mutation (a plugin toggled, an
 * agent activated) that changes what one of them reports; SWR refetches
 * each key in place, so mounted readers update without a remount.
 */
export function invalidateCatalog(): void {
  for (const key of Object.values(CATALOG_KEYS)) void mutate(key);
}

/**
 * SWR key for the backend's active-agent pointer. It sits beside the
 * catalogs because the Agents page and the header AgentSelector both
 * read and write it — one key, so they can never hold two answers.
 */
export const ACTIVE_AGENT_KEY = `${API_BASE}/api/agents/active`;

/** What /api/agents/active answers. */
export interface ActiveResponse {
  agent: string | null;
}

/**
 * Read the backend's active-agent pointer.
 *
 * @returns The active agent, or null when none is set.
 * @throws When the request fails.
 */
export async function fetchActiveAgent(): Promise<ActiveResponse> {
  const resp = await fetch(ACTIVE_AGENT_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as { agent?: unknown };
  // A missing or oddly-typed agent is "none active", not a failure.
  return { agent: typeof data.agent === "string" ? data.agent : null };
}

/** localStorage key the header reads for offline display. */
const SELECTED_AGENT_KEY = "berg-selected-agent";

/**
 * Mirror the active agent into localStorage for offline display in the
 * header. An external-store write rather than component state, so it
 * belongs in an Effect; a failed read leaves the stored value alone
 * rather than clearing it, so the header still shows the last known
 * agent while the backend is unreachable.
 *
 * @param agent - The active agent, or null to clear the selection.
 */
export function storeActiveAgent(agent: string | null): void {
  try {
    if (agent) localStorage.setItem(SELECTED_AGENT_KEY, agent);
    else localStorage.removeItem(SELECTED_AGENT_KEY);
  } catch {
    // Private-mode storage: selection stays in memory only.
  }
}

/**
 * Read the plugin catalog.
 *
 * @returns The plugins the backend reports.
 * @throws When the request fails or the payload is not a plugin list.
 */
export async function fetchPlugins(): Promise<PluginInfo[]> {
  const resp = await fetch(CATALOG_KEYS.plugins);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as PluginsResponse;
  if (!Array.isArray(data.plugins)) {
    throw new Error("Malformed /api/plugins payload");
  }
  return data.plugins;
}

/**
 * Read the agent catalog.
 *
 * @returns The agents the backend reports.
 * @throws When the request fails or the payload is not an agent list.
 */
export async function fetchAgents(): Promise<AgentInfo[]> {
  const resp = await fetch(CATALOG_KEYS.agents);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  if (!Array.isArray(data)) throw new Error("Malformed /api/agents payload");
  return data as AgentInfo[];
}

/**
 * Read the router stats.
 *
 * @returns The stats payload (shape owned by the backend).
 * @throws When the request fails.
 */
export async function fetchRouterStats(): Promise<unknown> {
  const resp = await fetch(CATALOG_KEYS.routerStats);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.json();
}

/** One entry in the tool catalog the slash palette and executor read. */
export interface ToolInfo {
  name: string;
  description: string;
  source: string;
}

/** What the tools endpoint answers. */
interface ToolsResponse {
  tools?: ToolInfo[];
}

/**
 * Read the tool catalog (workspace file tools, run_task, the delegated
 * plan/implement entries).
 *
 * @returns The tools the backend reports.
 * @throws When the request fails or the payload is not a tool list.
 */
export async function fetchTools(): Promise<ToolInfo[]> {
  const resp = await fetch(CATALOG_KEYS.tools);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as ToolsResponse;
  if (!Array.isArray(data.tools))
    throw new Error("Malformed /api/tools payload");
  return data.tools;
}
