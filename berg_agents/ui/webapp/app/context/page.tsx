/*
 * <one line to give the program's name and a brief idea of what it does.>
 *
 * Copyright (c) 2026.
 *         Copyright (C) <year>  <name of author>
 *
 *         This program is free software: you can redistribute it and/or modify
 *         it under the terms of the GNU Affero General Public License as
 *         published by the Free Software Foundation, either version 3 of the
 *         License, or (at your option) any later version.
 *
 *         This program is distributed in the hope that it will be useful,
 *         but WITHOUT ANY WARRANTY; without even the implied warranty of
 *         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *         GNU Affero General Public License for more details.
 *
 *         You should have received a copy of the GNU Affero General Public License
 *         along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 */

/*
 * Context page - everything the agent may load as shared context.
 * Memory files, skills, and MCP servers come from /api/context
 * (mirrors the TUI /memory /skills /mcps listings); learning stats
 * ride along in compact form instead of owning a tab.
 */

"use client";

import { useEffect, useState } from "react";
import { Card, Chip, Spinner } from "@heroui/react";

import { API_BASE } from "@/envConfig";

import { LearningPanel } from "../components/LearningPanel.tsx";
import { Navbar } from "../components/Navbar.tsx";

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
 * ContextPage - client component showing the shared context catalog:
 * memory files, skills, MCP servers, and compact learning stats.
 */
export default function ContextPage() {
  const [data, setData] = useState<ContextData | null>(null);
  const [stats, setStats] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [ctxRes, statsRes] = await Promise.all([
          fetch(`${API_BASE}/api/context`),
          fetch(`${API_BASE}/api/learning-stats`)]);
        if (!ctxRes.ok) throw new Error(`HTTP ${ctxRes.status}`);
        setData(await ctxRes.json());
        if (statsRes.ok) setStats(await statsRes.json());
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
        <Navbar />
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4">
            <Card variant="default">
              <Card.Content className="flex items-center justify-center py-8">
                <Spinner size="lg" />
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
        <Navbar />
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
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="text-2xl font-bold mb-4">Context</h1>
          <p className="text-sm text-muted-foreground mb-4">
            Everything the agent may load as shared context - memory
            files, skills, and MCP servers
            {data.active
              ? ` (chatting via ${data.active.provider} / ${data.active.model})`
              : ""}
            .
          </p>
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
                    className="flex items-center gap-2 text-sm"
                    key={m.path}
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
                    None configured in config/mcp.json.
                  </p>
                )}
                {data.mcp_servers.map((s) => (
                  <Chip
                    color={s.enabled ? "success" : "default"}
                    key={s.name}
                    size="sm"
                    variant="soft"
                  >
                    {s.name}
                    {s.enabled ? "" : " (off)"}
                  </Chip>
                ))}
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
              {data.skills.map((s) => (
                <div className="text-sm" key={s.name}>
                  <span className="font-mono font-semibold">{s.name}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    — {s.description || "no description"}
                  </span>
                </div>
              ))}
            </Card.Content>
          </Card>
          <div className="mt-3">
            <LearningPanel compact stats={stats as never} />
          </div>
        </div>
      </div>
    </>
  );
}
