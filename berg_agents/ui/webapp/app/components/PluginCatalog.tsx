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

"use client";

import { useCallback, useEffect, useState } from "react";

import { Button, Card, Chip } from "@heroui/react";
import { API_BASE } from "@/envConfig";

export interface PluginCapabilityInfo {
  type: string;
  id?: string;
  name?: string;
  server_type?: string;
  enabled?: boolean;
  sensitive?: boolean;
}

export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  state: string;
  description: string;
  tools: string[];
  capabilities: PluginCapabilityInfo[];
}

export interface PluginCatalogProps {
  /** Close the surface. */
  onClose?: () => void;
  /** Extra layout classes from the parent (width). */
  className?: string;
  /** Inline style from the host (e.g. draggable width). */
  style?: React.CSSProperties;
}

/**
 * Group a plugin for the catalog sections below.
 *
 * @param plugin - Plugin descriptor from /api/plugins.
 * @returns Section key: tool plugins, skills, MCP servers, or other.
 */
function sectionOf(plugin: PluginInfo): string {
  if (plugin.tools.length > 0) return "tools";
  if (plugin.capabilities.some((c) => c.type === "skill")) return "skills";
  if (plugin.capabilities.some((c) => c.type === "mcp")) return "mcp";
  return "other";
}

const SECTION_TITLE: Record<string, string> = {
  tools: "🔧 Tool plugins",
  skills: "📚 Skills",
  mcp: "🌐 MCP servers",
  other: "📦 Other"};

/**
 * Plugin catalog surface: every plugin the backend has loaded, grouped
 * by kind. Tool plugins show their chat tools, skills their catalog
 * entry, MCP servers their transport plus the approval flag — the same
 * data the model side uses, now visible to the user.
 */
export function PluginCatalog({
  onClose,
  className,
  style}: PluginCatalogProps) {
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);

  const fetchPlugins = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/plugins`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setPlugins(Array.isArray(data.plugins) ? data.plugins : []);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPlugins();
  }, [fetchPlugins]);

  // Enable/disable one plugin: the next chat turn picks up the change
  // (tools withheld, MCP toolsets and skills excluded server-side).
  const togglePlugin = async (plugin: PluginInfo) => {
    const enabled = plugin.state === "enabled";
    setToggling(plugin.id);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/${encodeURIComponent(plugin.id)}/${enabled ? "disable" : "enable"}`,
        { method: "POST" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchPlugins();
    } catch (e) {
      setError(String(e));
    } finally {
      setToggling(null);
    }
  };

  const sections = ["tools", "skills", "mcp", "other"]
    .map((key) => ({
      key,
      items: plugins.filter((p) => sectionOf(p) === key)}))
    .filter((s) => s.items.length > 0);

  return (
    <Card
      className={`mb-2 flex min-h-0 flex-col ${className ?? ""}`}
      style={style}
      variant="default"
    >
      <Card.Header>
        <Card.Title>🔌 Plugins</Card.Title>
        <Card.Description>
          {loading ? "Loading…" : `${plugins.length} loaded`}
        </Card.Description>
        <span className="flex-1" />
        <Button
          aria-label="Refresh plugins"
          size="sm"
          variant="secondary"
          onPress={() => {
            setLoading(true);
            void fetchPlugins();
          }}
        >
          ↻
        </Button>
        {onClose && (
          <Button
            aria-label="Close plugins"
            size="sm"
            variant="secondary"
            onPress={onClose}
          >
            ✕
          </Button>
        )}
      </Card.Header>
      <Card.Content className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-2">
        {error && <p className="text-xs text-red-500">{error}</p>}
        {sections.map((section) => (
          <div key={section.key} className="flex flex-col gap-1">
            <p className="text-xs font-semibold text-muted-foreground">
              {SECTION_TITLE[section.key]} ({section.items.length})
            </p>
            {section.items.map((plugin) => (
              <div
                key={plugin.id}
                className="rounded-md border border-border px-2 py-1"
                title={plugin.description}
              >
                <div className="flex items-center gap-1.5">
                  <span className="flex-1 truncate text-sm font-medium">
                    {plugin.name}
                  </span>
                  <Chip size="sm" variant="soft">
                    v{plugin.version}
                  </Chip>
                  <Chip
                    size="sm"
                    variant="soft"
                    color={plugin.state === "enabled" ? "success" : "default"}
                  >
                    {plugin.state}
                  </Chip>
                  <Button
                    aria-label={`${plugin.state === "enabled" ? "Disable" : "Enable"} ${plugin.name}`}
                    isDisabled={toggling === plugin.id}
                    size="sm"
                    variant="secondary"
                    onPress={() => void togglePlugin(plugin)}
                  >
                    {toggling === plugin.id
                      ? "…"
                      : plugin.state === "enabled"
                        ? "Disable"
                        : "Enable"}
                  </Button>
                </div>
                {plugin.tools.length > 0 && (
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {plugin.tools.join(", ")}
                  </p>
                )}
                {section.key === "mcp" && (
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {plugin.capabilities
                      .filter((c) => c.type === "mcp")
                      .map((c) => (
                        <span key={c.id}>
                          {c.server_type ?? "unknown"}
                          {c.sensitive ? " · needs approval" : ""}
                        </span>
                      ))}
                  </p>
                )}
              </div>
            ))}
          </div>
        ))}
        {plugins.length === 0 && !loading && !error && (
          <p className="text-xs text-muted-foreground">
            No plugins loaded — check the backend log.
          </p>
        )}
      </Card.Content>
    </Card>
  );
}

export default PluginCatalog;
