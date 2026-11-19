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
 *
 * Each catalog is one `useSWR` call against the shared key in
 * lib/backendCatalog, so this hook holds no fetch, no effect and no
 * loading bookkeeping of its own: SWR owns the request, the cache, the
 * deduplication across readers, and the error/empty distinction (a
 * failed read keeps the last good list instead of blanking it). The hook
 * only narrows SWR's `{ data, error }` to the three fields App draws.
 */

import type { AgentInfo } from "@/harness";
import type { ToolInfo } from "@/lib/backendCatalog";

import useSWR from "swr";

import {
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchAgents,
  fetchRouterStats,
  fetchTools} from "@/lib/backendCatalog";

/** The three catalogs, each independently loadable. */
export interface BackendCatalog {
  /** Workspace file tools, run_task, and the delegated plan/implement
        entries, each with a one-line description. */
  backendTools: ToolInfo[];
  /** The agent list for the selector. */
  agents: AgentInfo[];
  /** Router stats for the stats panel, or null before they arrive. */
  routerStats: unknown;
}

/**
 * Read the backend's three catalogs, on mount and on the shared cadence.
 *
 * @returns The three catalogs (each empty or null until it loads).
 */
export function useBackendCatalog(): BackendCatalog {
  // One SWR reader per catalog. `?? []` / `?? null` only cover the
  // not-yet-loaded case; a failed read surfaces as `error` on that same
  // key and leaves these at their last good value, which is what keeps a
  // backend blip from blanking the chrome. CATALOG_SWR_OPTIONS adds the
  // re-poll, so a tool or agent added on disk reaches the chrome without
  // a reload.
  const { data: tools } = useSWR<ToolInfo[]>(
    CATALOG_KEYS.tools,
    fetchTools,
    CATALOG_SWR_OPTIONS,
  );
  const { data: agents } = useSWR<AgentInfo[]>(
    CATALOG_KEYS.agents,
    fetchAgents,
    CATALOG_SWR_OPTIONS,
  );
  const { data: routerStats } = useSWR<unknown>(
    CATALOG_KEYS.routerStats,
    fetchRouterStats,
    CATALOG_SWR_OPTIONS,
  );

  return {
    backendTools: tools ?? [],
    agents: agents ?? [],
    routerStats: routerStats ?? null};
}
