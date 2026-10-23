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

/* Plugin dev mode — a standalone page for working on plugin surfaces.
 *
 * The chat app only mounts a plugin's UI in reaction to a live agent
 * tool call, so before this page there was no way to open a plugin's
 * surface on its own. This route mounts PluginUISurface directly and
 * drives the plugin's own tools through the same host endpoints the
 * chat uses, so a plugin can be developed and exercised without a
 * running agent or a real conversation.
 *
 * Contract (mirrors app/plugins/registry.tsx and ui/routes.py):
 *   GET  /api/plugins                     -> {plugins:[{...,ui:{entry_url,export,...}}]}
 *   POST /api/plugins/{id}/tools/{name}   -> {plugin,tool,result} | 404 (unknown) | 502 (raised)
 *   POST /api/plugins/{id}/enable|disable -> {id,state}
 *
 * Plugin bundles resolve React/HeroUI against window.BergRuntime. The
 * `/` route installs that runtime in client.tsx; this route does not
 * go through client.tsx, so it installs the runtime itself (idempotent).
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Card, Chip, Spinner } from "@heroui/react";

import { API_BASE } from "@/envConfig";
import { installBergRuntime } from "../../runtime/berg-runtime.ts";
import { PluginUISurface } from "../../plugins/PluginUISurface.tsx";
import { Navbar } from "../../components/Navbar.tsx";

/** `ui:` block a plugin's manifest declares, as served by /api/plugins. */
interface PluginUiDeclaration {
  entry?: string;
  export?: string;
  entry_url?: string;
  entry_built?: boolean;
  placement?: string;
  label?: string;
  width?: number;
}

/** One capability descriptor from /api/plugins. */
interface PluginCapabilityInfo {
  type: string;
  id?: string;
  name?: string;
  sensitive?: boolean;
}

/** Plugin descriptor from /api/plugins (superset of the chat-side shape). */
interface PluginDescriptor {
  id: string;
  name: string;
  version: string;
  state: string;
  description: string;
  tools: string[];
  capabilities: PluginCapabilityInfo[];
  ui?: PluginUiDeclaration | null;
}

/**
 * Plugin dev page — mount any plugin's surface and call its tools
 * directly, without a live agent run.
 */
export default function PluginDevPage() {
  const [plugins, setPlugins] = useState<PluginDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"panel" | "canvas">("canvas");
  const [refreshKey, setRefreshKey] = useState(0);

  // Tool runner state (reset whenever the selected plugin changes).
  const [tool, setTool] = useState<string | null>(null);
  const [argsText, setArgsText] = useState("{}");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [toolError, setToolError] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);

  // Plugin UI bundles resolve against window.BergRuntime; install it on
  // this route too (client.tsx only covers the `/` route). Idempotent.
  useEffect(() => {
    installBergRuntime();
  }, []);

  const fetchPlugins = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/plugins`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setPlugins(Array.isArray(data.plugins) ? data.plugins : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPlugins();
  }, [fetchPlugins]);

  // Auto-select the first plugin once the catalog arrives; explicit
  // selections (setSelectedId + reset) override afterwards.
  const selected =
    plugins.find((p) => p.id === selectedId) ?? plugins[0] ?? null;

  // Default the tool runner to the plugin's first tool whenever the
  // selection changes, so the panel is immediately usable.
  useEffect(() => {
    setTool(selected?.tools?.[0] ?? null);
    setArgsText("{}");
    setResult(null);
    setToolError(null);
  }, [selected?.id]);

  /** Select a plugin and clear any prior tool-run output. */
  const selectPlugin = (id: string) => {
    setSelectedId(id);
    setRefreshKey((k) => k + 1);
  };

  /** Enable/disable the selected plugin through the host endpoints. */
  const togglePlugin = async (plugin: PluginDescriptor) => {
    const enabled = plugin.state === "enabled";
    setToggling(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/plugins/${encodeURIComponent(plugin.id)}/${enabled ? "disable" : "enable"}`,
        { method: "POST" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await fetchPlugins();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setToggling(false);
    }
  };

  /**
   * Run one of the selected plugin's tools exactly like the chat does.
   * The body is the tool's own kwargs (host strips sessionId/tool/args).
   */
  const runTool = async (plugin: PluginDescriptor, toolName: string) => {
    setRunning(true);
    setResult(null);
    setToolError(null);
    try {
      const body = JSON.parse(argsText || "{}") as Record<string, unknown>;
      const resp = await fetch(
        `${API_BASE}/api/plugins/${encodeURIComponent(plugin.id)}/tools/${encodeURIComponent(toolName)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)},
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setToolError(`HTTP ${resp.status}: ${data?.detail ?? resp.statusText}`);
      } else {
        // Tools return a human string for the model; structured returns
        // arrive JSON-encoded. Show the raw payload either way.
        setResult(
          typeof data.result === "string"
            ? data.result
            : JSON.stringify(data.result, null, 2),
        );
      }
    } catch (e) {
      // A JSON.parse failure lands here too; message is clear enough.
      setToolError(e instanceof Error ? e.message : "Tool call failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="text-2xl font-bold mb-1">Plugin Dev Mode</h1>
          <p className="text-sm text-muted-foreground mb-4">
            Standalone harness for plugin surfaces: mount a plugin&apos;s UI and
            call its tools without a running agent. Surfaces resolve React /
            HeroUI against the host runtime (<code>window.BergRuntime</code>),
            exactly as they do inside chat.
          </p>

          {loading && (
            <Card variant="default">
              <Card.Content className="flex items-center gap-2 py-6">
                <Spinner size="sm" />
                <span className="text-sm text-muted-foreground">
                  Loading plugins…
                </span>
              </Card.Content>
            </Card>
          )}

          {error && <p className="mb-3 text-xs text-red-500">{error}</p>}

          {!loading && plugins.length === 0 && !error && (
            <Card variant="default">
              <Card.Content className="py-6">
                <p className="text-sm text-muted-foreground">
                  No plugins discovered. Start the app with plugins configured
                  and they appear here.
                </p>
              </Card.Content>
            </Card>
          )}

          {plugins.length > 0 && (
            <>
              {/* Plugin picker */}
              <div className="mb-4 flex flex-wrap gap-2">
                {plugins.map((p) => (
                  <Button
                    key={p.id}
                    size="sm"
                    variant={selected?.id === p.id ? "primary" : "secondary"}
                    onPress={() => selectPlugin(p.id)}
                  >
                    {p.name}
                  </Button>
                ))}
              </div>

              {selected && (
                <div className="grid gap-3 md:grid-cols-2">
                  {/* Surface preview */}
                  <Card variant="default">
                    <Card.Header>
                      <Card.Title>{selected.name} surface</Card.Title>
                      <Card.Description>
                        {selected.ui?.label ?? selected.name}
                        {selected.ui?.placement
                          ? ` · ${selected.ui.placement}`
                          : ""}
                      </Card.Description>
                    </Card.Header>
                    <Card.Content>
                      <div className="mb-2 flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onPress={() =>
                            setView(view === "panel" ? "canvas" : "panel")
                          }
                        >
                          {view === "panel" ? "Canvas view" : "Panel view"}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onPress={() => setRefreshKey((k) => k + 1)}
                        >
                          ↻ Refresh
                        </Button>
                      </div>
                      {selected.ui && selected.ui.entry_url ? (
                        <div
                          className="rounded-md border border-border p-2"
                          style={
                            view === "panel"
                              ? { maxWidth: selected.ui.width ?? 340 }
                              : undefined
                          }
                        >
                          <PluginUISurface
                            pluginId={selected.id}
                            ui={selected.ui as Record<string, unknown>}
                            view={view}
                            refreshKey={refreshKey}
                          />
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          This plugin declares no loadable UI surface
                          {selected.ui?.entry_built === false
                            ? " — its bundle has not been built. Run the plugin's build:ui script."
                            : " (no ui: block in its manifest)."}
                        </p>
                      )}
                    </Card.Content>
                  </Card>

                  {/* Tool runner */}
                  <Card variant="default">
                    <Card.Header>
                      <Card.Title>Tools ({selected.tools.length})</Card.Title>
                      <Card.Description>
                        Call the plugin&apos;s own tools directly.
                      </Card.Description>
                    </Card.Header>
                    <Card.Content className="flex flex-col gap-3">
                      {selected.tools.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          This plugin registers no tools.
                        </p>
                      )}
                      {selected.tools.length > 0 && (
                        <>
                          <div className="flex flex-wrap gap-2">
                            {selected.tools.map((t) => (
                              <Button
                                key={t}
                                size="sm"
                                variant={tool === t ? "primary" : "secondary"}
                                onPress={() => {
                                  setTool(t);
                                  setResult(null);
                                  setToolError(null);
                                }}
                              >
                                {t}
                              </Button>
                            ))}
                          </div>
                          <label
                            className="text-xs font-semibold text-muted-foreground"
                            htmlFor="dev-plugin-tool-args"
                          >
                            Arguments (JSON kwargs)
                          </label>
                          <textarea
                            id="dev-plugin-tool-args"
                            className="input-bar-textarea"
                            rows={3}
                            spellCheck={false}
                            value={argsText}
                            onChange={(e) => setArgsText(e.target.value)}
                          />
                          <div>
                            <Button
                              variant="primary"
                              isDisabled={!tool || running}
                              onPress={() =>
                                tool && void runTool(selected, tool)
                              }
                            >
                              {running ? "Running…" : `Run ${tool ?? ""}`}
                            </Button>
                          </div>
                          {toolError && (
                            <p className="text-xs text-red-500">{toolError}</p>
                          )}
                          {result !== null && (
                            <pre className="max-h-64 overflow-auto rounded-md border border-border bg-background p-2 text-xs">
                              {result}
                            </pre>
                          )}
                        </>
                      )}
                    </Card.Content>
                  </Card>

                  {/* Metadata: state, description, capabilities */}
                  <Card className="md:col-span-2" variant="default">
                    <Card.Content className="flex flex-col gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Chip
                          color={
                            selected.state === "enabled" ? "success" : "default"
                          }
                          size="sm"
                          variant="soft"
                        >
                          {selected.state}
                        </Chip>
                        <span className="text-sm text-muted-foreground">
                          v{selected.version}
                        </span>
                        <span className="flex-1" />
                        <Button
                          size="sm"
                          variant="secondary"
                          isDisabled={toggling}
                          onPress={() => void togglePlugin(selected)}
                        >
                          {selected.state === "enabled" ? "Disable" : "Enable"}
                        </Button>
                      </div>
                      {selected.description && (
                        <p className="text-sm">{selected.description}</p>
                      )}
                      {selected.capabilities.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {selected.capabilities.map((c, i) => (
                            <Chip
                              key={`${c.type}-${c.id ?? c.name ?? i}`}
                              size="sm"
                              variant="soft"
                            >
                              {c.type}
                              {c.sensitive ? " 🔒" : ""}
                            </Chip>
                          ))}
                        </div>
                      )}
                    </Card.Content>
                  </Card>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
