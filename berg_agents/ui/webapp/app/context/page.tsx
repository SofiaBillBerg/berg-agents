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
 * Context page - everything the agent may load as shared context.
 * Memory files, skills, and MCP servers come from /api/context
 * (mirrors the TUI /memory /skills /mcps listings); router stats
 * ride along in compact form instead of owning a tab.
 */

"use client";

import type { PluginInfo } from "@/lib/backendCatalog";

import useSWR from "swr";

import { RouterStatsPanel } from "../components/RouterStatsPanel.tsx";
import { SharedContextEditor } from "../components/SharedContextEditor.tsx";
import { Navbar } from "../components/Navbar.tsx";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle} from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import {
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchPlugins,
  fetchRouterStats} from "@/lib/backendCatalog";
import { API_BASE } from "@/envConfig";

interface MemoryEntry {
  path: string;
  exists: boolean;
}

interface SkillEntry {
  name: string;
  description: string;
  source: string;
}

interface McpEntry {
  name: string;
  enabled: boolean;
}

interface ContextData {
  memory: MemoryEntry[];
  skills: SkillEntry[];
  mcp_servers: McpEntry[];
  active: { provider: string; model: string } | null;
}

/**
 * Normalize a skill name for cross-source matching: the context
 * catalog uses `skill-<name>` ids while plugin metadata carries the
 * bare catalog name (occasionally with different casing).
 */
function skillKey(name: string): string {
  return name.toLowerCase().replace(/^skill-/, "");
}

/**
 * Index plugins by kind for the runtime overlays below.
 *
 * @param plugins - Descriptors from /api/plugins.
 * @returns MCP server map, skill map, and tool-plugin list.
 */
function indexPlugins(plugins: PluginInfo[]): {
  mcp: Map<string, PluginInfo>;
  skills: Map<string, PluginInfo>;
  toolPlugins: PluginInfo[];
} {
  const mcp = new Map<string, PluginInfo>();
  const skills = new Map<string, PluginInfo>();
  const toolPlugins: PluginInfo[] = [];
  for (const p of plugins) {
    if (p.tools.length > 0) toolPlugins.push(p);
    for (const c of p.capabilities) {
      if (c.type === "mcp" && c.id) mcp.set(c.id, p);
      if (c.type === "skill") skills.set(skillKey(c.name ?? c.id ?? ""), p);
    }
    // Disabled plugins carry synthesized descriptors (or none for
    // tool plugins) — still index MCP/skill identity by plugin id.
    if (p.id.startsWith("berg-plugin-mcp-")) {
      mcp.set(p.id.replace("berg-plugin-mcp-", ""), p);
    }
  }
  return { mcp, skills, toolPlugins };
}

/**
 * Read /api/context — memory files, skills, MCP servers and the active
 * model. Only this page consumes it, so the fetcher lives here rather
 * than in the shared catalog module.
 *
 * @returns The context catalog.
 * @throws When the request fails.
 */
async function fetchContext(): Promise<ContextData> {
  const resp = await fetch(`${API_BASE}/api/context`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as ContextData;
}

const SUCCESS_BADGE_CLASS =
  "border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-400";

/**
 * ContextPage - client component showing the shared context catalog:
 * memory files, skills, MCP servers, and compact router stats.
 *
 * Three independent SWR readers rather than one Promise.all: the plugin
 * and stats reads are best-effort (their own comment says the catalog
 * must still render when the plugin system is down), and bundling them
 * into a single all-or-nothing await made one outage fail the page.
 * Each key now fails, or succeeds, on its own.
 */
export default function ContextPage() {
  const { data, error, isLoading } = useSWR<ContextData>(
    `${API_BASE}/api/context`,
    fetchContext,
  );
  const { data: plugins = [] } = useSWR<PluginInfo[]>(
    CATALOG_KEYS.plugins,
    fetchPlugins,
    CATALOG_SWR_OPTIONS,
  );
  const { data: stats } = useSWR<unknown>(
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
                <span className="ml-2">Loading context...</span>
              </CardContent>
            </Card>
          </div>
        </div>
      </>
    );
  }

  if (error || !data) {
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
                  Failed to load context: {error?.message ?? "empty response"}
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </>
    );
  }

  const { mcp, skills, toolPlugins } = indexPlugins(plugins);

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="mb-4 text-2xl font-bold">Context</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            Everything the agent may load as shared context - memory files,
            skills, and MCP servers
            {data.active
              ? ` (chatting via ${data.active.provider} / ${data.active.model})`
              : ""}
            . Runtime state comes from the plugin system
            {plugins.length > 0 ? ` (${plugins.length} plugins)` : ""}.
          </p>

          {/* user-owned Shared Context: view/edit it in-app (E1). */}
          <div className="mb-4">
            <SharedContextEditor />
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Memory files</CardTitle>
                <CardDescription>
                  Always-loaded AGENTS.md paths ({data.memory.length})
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-1.5">
                {data.memory.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    None configured - set BERG_AGENT_MEMORY to share context
                    files with the agent.
                  </p>
                )}
                {data.memory.map((m) => (
                  <div key={m.path} className="flex items-center gap-2 text-sm">
                    <span className="truncate font-mono">{m.path}</span>
                    <Badge
                      className={m.exists ? SUCCESS_BADGE_CLASS : undefined}
                      variant={m.exists ? "outline" : "destructive"}
                    >
                      {m.exists ? "found" : "missing"}
                    </Badge>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>MCP servers</CardTitle>
                <CardDescription>
                  External tools ({data.mcp_servers.length})
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {data.mcp_servers.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    None configured in .berg-agents/mcp.json.
                  </p>
                )}
                {data.mcp_servers.map((s) => {
                  const plugin = mcp.get(s.name);
                  const runtimeOff = plugin
                    ? plugin.state !== "enabled"
                    : !s.enabled;
                  const sensitive = plugin?.capabilities.some(
                    (c) => c.type === "mcp" && c.sensitive,
                  );
                  return (
                    <Badge
                      key={s.name}
                      className={runtimeOff ? undefined : SUCCESS_BADGE_CLASS}
                      title={
                        plugin
                          ? `${plugin.state}${sensitive ? " · tools need approval" : ""}`
                          : "plugin system unavailable"
                      }
                      variant={runtimeOff ? "secondary" : "outline"}
                    >
                      {s.name}
                      {runtimeOff ? " (off)" : ""}
                      {sensitive ? " 🔒" : ""}
                    </Badge>
                  );
                })}
              </CardContent>
            </Card>
          </div>
          <Card className="mt-3">
            <CardHeader>
              <CardTitle>Skills ({data.skills.length})</CardTitle>
              <CardDescription>
                SKILL.md manuals, loaded on demand
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {data.skills.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  None found - point BERG_AGENT_SKILLS at a skills directory.
                </p>
              )}
              {data.skills.map((s) => {
                const plugin = skills.get(skillKey(s.name));
                const enabled = plugin?.state === "enabled";
                return (
                  <div key={s.name} className="text-sm">
                    <span className="font-mono font-semibold">{s.name}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      - {s.description || "no description"}
                    </span>{" "}
                    {plugin && (
                      <Badge
                        className={enabled ? SUCCESS_BADGE_CLASS : undefined}
                        variant={enabled ? "outline" : "secondary"}
                      >
                        {enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    )}
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {toolPlugins.length > 0 && (
            <Card className="mt-3">
              <CardHeader>
                <CardTitle>Tool plugins ({toolPlugins.length})</CardTitle>
                <CardDescription>
                  Plugin tools offered to the chat agent
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {toolPlugins.map((p) => {
                  const enabled = p.state === "enabled";
                  return (
                    <div key={p.id} className="text-sm">
                      <span className="font-semibold">{p.name}</span>{" "}
                      <Badge variant="secondary">v{p.version}</Badge>{" "}
                      <Badge
                        className={enabled ? SUCCESS_BADGE_CLASS : undefined}
                        variant={enabled ? "outline" : "secondary"}
                      >
                        {p.state}
                      </Badge>
                      <div className="font-mono text-[11px] text-muted-foreground">
                        {p.tools.join(", ")}
                      </div>
                    </div>
                  );
                })}
              </CardContent>
            </Card>
          )}

          <div className="mt-3">
            <RouterStatsPanel compact stats={stats as never} />
          </div>
        </div>
      </div>
    </>
  );
}
