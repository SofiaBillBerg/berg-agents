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
 * Context page - everything the agent may load as shared context.
 * Memory files, skills, and MCP servers come from /api/context
 * (mirrors the TUI /memory /skills /mcps listings); router stats
 * ride along in compact form instead of owning a tab.
 */

"use client";

import type {PluginInfo} from "../components/PluginCatalog.tsx";

import {useEffect, useState} from "react";
import {Card, Chip, Spinner} from "@heroui/react";


import {RouterStatsPanel} from "../components/RouterStatsPanel.tsx";
import {SharedContextEditor} from "../components/SharedContextEditor.tsx";
import {Navbar} from "../components/Navbar.tsx";

import {API_BASE} from "@/envConfig";

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
    return {mcp, skills, toolPlugins};
}

/**
 * ContextPage - client component showing the shared context catalog:
 * memory files, skills, MCP servers, and compact router stats.
 */
export default function ContextPage() {
    const [data, setData] = useState<ContextData | null>(null);
    const [plugins, setPlugins] = useState<PluginInfo[]>([]);
    const [stats, setStats] = useState<unknown>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchAll = async () => {
            try {
                // NOTE: /api/plugins is best-effort — the config-driven
                // catalog below still renders when the plugin system is down.
                const [ctxRes, statsRes, pluginsRes] = await Promise.all([
                    fetch(`${API_BASE}/api/context`),
                    fetch(`${API_BASE}/api/router-stats`),
                    fetch(`${API_BASE}/api/plugins`)]);
                if (!ctxRes.ok) throw new Error(`HTTP ${ctxRes.status}`);
                setData(await ctxRes.json());
                if (statsRes.ok) setStats(await statsRes.json());
                if (pluginsRes.ok) {
                    const body = await pluginsRes.json();
                    if (Array.isArray(body.plugins)) setPlugins(body.plugins);
                }
            } catch (err) {
                setError(err instanceof Error ? err.message : "Network error");
            } finally {
                setLoading(false);
            }
        };
        void fetchAll();
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
                                <span className="ml-2">Loading context...</span>
                            </Card.Content>
                        </Card>
                    </div>
                </div>
            </>
        );
    }

    if (error || !data) {
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
                                <p className="text-sm">
                                    Failed to load context: {error ?? "empty response"}
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
            <Navbar/>
            <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-6xl p-4">
                    <h1 className="text-2xl font-bold mb-4">Context</h1>
                    <p className="text-sm text-muted-foreground mb-4">
                        Everything the agent may load as shared context - memory files,
                        skills, and MCP servers
                        {data.active
                            ? ` (chatting via ${data.active.provider} / ${data.active.model})`
                            : ""}
                        . Runtime state comes from the plugin system
                        {plugins.length > 0 ? ` (${plugins.length} plugins)` : ""}.
                    </p>
                    {/* Human-owned Shared Context: view/edit it in-app (E1). */}
                    <div className="mb-4">
                        <SharedContextEditor/>
                    </div>
                    {/* NOTE: Runtime overlay — config lists what exists, the
              plugin map adds live state (toggled off, approval flags). */}
                    {(() => {
                        const {mcp, skills, toolPlugins} = indexPlugins(plugins);
                        return (
                            <>
                                <div className="grid gap-3 md:grid-cols-2">
                                    <Card variant="default">
                                        <Card.Header>
                                            <Card.Title>Memory files</Card.Title>
                                            <Card.Description>
                                                Always-loaded AGENTS.md paths ({data.memory.length})
                                            </Card.Description>
                                        </Card.Header>
                                        <Card.Content className="flex flex-col gap-1.5">
                                            {data.memory.length === 0 && (
                                                <p className="text-sm text-muted-foreground">
                                                    None configured - set BERG_AGENT_MEMORY to share
                                                    context files with the agent.
                                                </p>
                                            )}
                                            {data.memory.map((m) => (
                                                <div
                                                    key={m.path}
                                                    className="flex items-center gap-2 text-sm"
                                                >
                                                    <span className="font-mono truncate">{m.path}</span>
                                                    <Chip
                                                        color={m.exists ? "success" : "danger"}
                                                        size="sm"
                                                        variant="soft"
                                                    >
                                                        {m.exists ? "found" : "missing"}
                                                    </Chip>
                                                </div>
                                            ))}
                                        </Card.Content>
                                    </Card>
                                    <Card variant="default">
                                        <Card.Header>
                                            <Card.Title>MCP servers</Card.Title>
                                            <Card.Description>
                                                External tools ({data.mcp_servers.length})
                                            </Card.Description>
                                        </Card.Header>
                                        <Card.Content className="flex flex-wrap gap-1.5">
                                            {data.mcp_servers.length === 0 && (
                                                <p className="text-sm text-muted-foreground">
                                                    None configured in .berg-agents/mcp.json.
                                                </p>
                                            )}
                                            {data.mcp_servers.map((s) => {
                                                const plugin = mcp.get(s.name);
                                                // Runtime state is authoritative: the sidepanel
                                                // toggle changes it, and the config flag is only the
                                                // startup default. Reading the flag here is what made
                                                // the two views disagree (enabled in the panel, "off"
                                                // in this tab).
                                                const runtimeOff = plugin
                                                    ? plugin.state !== "enabled"
                                                    : !s.enabled;
                                                const sensitive = plugin?.capabilities.some(
                                                    (c) => c.type === "mcp" && c.sensitive,
                                                );
                                                return (
                                                    <Chip
                                                        key={s.name}
                                                        color={runtimeOff ? "default" : "success"}
                                                        size="sm"
                                                        title={
                                                            plugin
                                                                ? `${plugin.state}${sensitive ? " · tools need approval" : ""}`
                                                                : "plugin system unavailable"
                                                        }
                                                        variant="soft"
                                                    >
                                                        {s.name}
                                                        {runtimeOff ? " (off)" : ""}
                                                        {sensitive ? " 🔒" : ""}
                                                    </Chip>
                                                );
                                            })}
                                        </Card.Content>
                                    </Card>
                                </div>
                                <Card className="mt-3" variant="default">
                                    <Card.Header>
                                        <Card.Title>Skills ({data.skills.length})</Card.Title>
                                        <Card.Description>
                                            SKILL.md manuals, loaded on demand
                                        </Card.Description>
                                    </Card.Header>
                                    <Card.Content className="flex flex-col gap-2">
                                        {data.skills.length === 0 && (
                                            <p className="text-sm text-muted-foreground">
                                                None found - point BERG_AGENT_SKILLS at a skills
                                                directory.
                                            </p>
                                        )}
                                        {data.skills.map((s) => {
                                            const plugin = skills.get(skillKey(s.name));
                                            return (
                                                <div key={s.name} className="text-sm">
                          <span className="font-mono font-semibold">
                            {s.name}
                          </span>
                                                    <span className="text-muted-foreground">
                            {" "}
                                                        — {s.description || "no description"}
                          </span>{" "}
                                                    {plugin && (
                                                        <Chip
                                                            color={
                                                                plugin.state === "enabled"
                                                                    ? "success"
                                                                    : "default"
                                                            }
                                                            size="sm"
                                                            variant="soft"
                                                        >
                                                            {plugin.state === "enabled"
                                                                ? "Enabled"
                                                                : "Disabled"}
                                                        </Chip>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </Card.Content>
                                </Card>
                                {toolPlugins.length > 0 && (
                                    <Card className="mt-3" variant="default">
                                        <Card.Header>
                                            <Card.Title>
                                                Tool plugins ({toolPlugins.length})
                                            </Card.Title>
                                            <Card.Description>
                                                Plugin tools offered to the chat agent
                                            </Card.Description>
                                        </Card.Header>
                                        <Card.Content className="flex flex-col gap-2">
                                            {toolPlugins.map((p) => (
                                                <div key={p.id} className="text-sm">
                                                    <span className="font-semibold">{p.name}</span>{" "}
                                                    <Chip size="sm" variant="soft">
                                                        v{p.version}
                                                    </Chip>{" "}
                                                    <Chip
                                                        color={
                                                            p.state === "enabled" ? "success" : "default"
                                                        }
                                                        size="sm"
                                                        variant="soft"
                                                    >
                                                        {p.state}
                                                    </Chip>
                                                    <div className="font-mono text-[11px] text-muted-foreground">
                                                        {p.tools.join(", ")}
                                                    </div>
                                                </div>
                                            ))}
                                        </Card.Content>
                                    </Card>
                                )}
                                <div className="mt-3">
                                    <RouterStatsPanel compact stats={stats as never}/>
                                </div>
                            </>
                        );
                    })()}
                </div>
            </div>
        </>
    );
}
