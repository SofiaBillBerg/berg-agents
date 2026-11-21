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
 * Stats page - router statistics and model performance metrics.
 * Fetches stats from /api/stats on the client.
 */

"use client";

import useSWR from "swr";

import { RouterStatsPanel } from "../components/RouterStatsPanel.tsx";
import { Navbar } from "../components/Navbar.tsx";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchRouterStats} from "@/lib/backendCatalog";

/**
 * StatsPage - client component displaying router outcome statistics.
 */
export default function StatsPage() {
  const {
    data: stats,
    error,
    isLoading} = useSWR<unknown>(
    CATALOG_KEYS.routerStats,
    fetchRouterStats,
    CATALOG_SWR_OPTIONS,
  );

  if (isLoading) {
    return (
      <>
        <Navbar />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4">
            <Card>
              <CardContent className="flex items-center justify-center py-8">
                <Spinner className="size-6" />
                <span className="ml-2">Loading statistics...</span>
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
                <p className="text-sm">Failed to load stats: {error.message}</p>
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
          <h1 className="mb-2 text-2xl font-bold">Statistics</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            Berg learns which models succeed on which tasks — these numbers
            steer future routing automatically.
          </p>
          <RouterStatsPanel stats={stats as never} />
        </div>
      </div>
    </>
  );
}
