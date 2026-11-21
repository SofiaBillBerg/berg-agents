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
"use client";

import { useEffect, useState } from "react";

import { PluginUISurface } from "../../plugins/PluginUISurface.tsx";
import { Navbar } from "../../components/Navbar.tsx";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE } from "@/envConfig";

interface PluginSummary {
  id: string;
  name?: string;
  version?: string;
  state?: string;
  description?: string;
  tools?: string[];
  ui?: Record<string, unknown> | null;
}

export default function DevPluginsPage() {
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [view, setView] = useState<"panel" | "canvas">("canvas");
  const [refreshKey, setRefreshKey] = useState(0);
  const [uiDraft, setUiDraft] = useState("");
  const [uiOverride, setUiOverride] = useState<Record<string, unknown> | null>(
    null,
  );
  const [draftError, setDraftError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("plugin");
    void fetch(`${API_BASE}/api/plugins`)
      .then((res) =>
        res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)),
      )
      .then((data: { plugins?: PluginSummary[] }) => {
        const all = data.plugins ?? [];
        setPlugins(all);
        const withUi = all.filter((p) => p.ui != null);
        const match =
          withUi.find((p) => p.id === requested) ?? withUi[0] ?? null;
        if (match) {
          setActiveId(match.id);
          setUiDraft(JSON.stringify(match.ui, null, 2));
          setUiOverride(null);
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  const active = plugins.find((p) => p.id === activeId) ?? null;
  const effectiveUi = active ? (uiOverride ?? active.ui ?? null) : null;

  const selectPlugin = (plugin: PluginSummary) => {
    setActiveId(plugin.id);
    setUiOverride(null);
    setDraftError(null);
    setUiDraft(plugin.ui ? JSON.stringify(plugin.ui, null, 2) : "{}");
  };

  const applyUiDraft = () => {
    try {
      const parsed: unknown = JSON.parse(uiDraft);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed)
      ) {
        setDraftError("Must be a JSON object.");
        return;
      }
      setUiOverride(parsed as Record<string, unknown>);
      setDraftError(null);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <Navbar />
      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-6xl flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h1 className="text-lg font-semibold">Plugin UI workbench</h1>
              <p className="text-xs text-muted-foreground">
                Inspects all installed plugins from <code>/api/plugins</code>{" "}
                and mounts declared <code>ui:</code> surfaces against{" "}
                <code>window.BergRuntime</code>.
              </p>
            </div>
            {active?.ui && (
              <div className="flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant={view === "panel" ? "default" : "secondary"}
                  onPress={() => setView("panel")}
                >
                  ◫ Panel
                </Button>
                <Button
                  size="sm"
                  variant={view === "canvas" ? "default" : "secondary"}
                  onPress={() => setView("canvas")}
                >
                  ⛶ Canvas
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onPress={() => setRefreshKey((k) => k + 1)}
                >
                  ↻ Remount
                </Button>
              </div>
            )}
          </div>

          {error && (
            <Card className="border-destructive">
              <CardHeader>
                <CardTitle className="text-destructive">
                  Could not reach /api/plugins
                </CardTitle>
              </CardHeader>
              <CardContent className="text-xs">{error}</CardContent>
            </Card>
          )}

          {/* All installed plugins selector */}
          {plugins.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Installed plugins ({plugins.length})
                </CardTitle>
                <CardDescription>
                  Select any plugin to inspect its manifest or mount its UI
                  surface.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {plugins.map((p) => {
                  const isSelected = p.id === activeId;
                  const hasUi = p.ui != null;
                  return (
                    <Button
                      key={p.id}
                      size="sm"
                      variant={isSelected ? "default" : "secondary"}
                      onPress={() => selectPlugin(p)}
                    >
                      <span>{p.name ?? p.id}</span>
                      {hasUi && (
                        <Badge className="ml-1.5" variant="outline">
                          UI
                        </Badge>
                      )}
                    </Button>
                  );
                })}
              </CardContent>
            </Card>
          )}

          {!error && plugins.length === 0 && (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                No plugins reported by <code>/api/plugins</code>.
              </CardContent>
            </Card>
          )}

          {/* Workspace: mounted surface + manifest/UI editor */}
          {active && (
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                {effectiveUi ? (
                  <div className="rounded-xl border border-border p-2">
                    <PluginUISurface
                      pluginId={active.id}
                      refreshKey={refreshKey}
                      ui={effectiveUi}
                      view={view}
                      onClose={() => setActiveId(null)}
                      onToggleView={() =>
                        setView((v) => (v === "panel" ? "canvas" : "panel"))
                      }
                    />
                  </div>
                ) : (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-sm">
                        {active.name ?? active.id}
                      </CardTitle>
                      <CardDescription>
                        This plugin has no declared <code>ui:</code> surface.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-2 text-xs text-muted-foreground">
                      {active.description && <p>{active.description}</p>}
                      {active.tools && active.tools.length > 0 && (
                        <p className="font-mono">
                          Tools: {active.tools.join(", ")}
                        </p>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>

              <Card className="h-fit">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">
                    Manifest & UI config
                  </CardTitle>
                  <CardDescription>
                    Edit the <code>ui:</code> payload passed to{" "}
                    <code>PluginUISurface</code>.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <Badge variant="secondary">{active.id}</Badge>
                    {active.version && (
                      <Badge variant="outline">v{active.version}</Badge>
                    )}
                    {active.state && (
                      <Badge variant="outline">{active.state}</Badge>
                    )}
                  </div>
                  <Textarea
                    aria-label="Plugin UI JSON config"
                    className="min-h-48 font-mono text-xs"
                    value={uiDraft}
                    onChange={(e) => setUiDraft(e.target.value)}
                  />
                  {draftError && (
                    <p className="text-xs text-destructive">{draftError}</p>
                  )}
                  <div className="flex gap-2">
                    <Button
                      isDisabled={!active.ui}
                      size="sm"
                      variant="default"
                      onPress={applyUiDraft}
                    >
                      Apply & reload
                    </Button>
                    <Button
                      isDisabled={!uiOverride}
                      size="sm"
                      variant="secondary"
                      onPress={() => {
                        setUiOverride(null);
                        setDraftError(null);
                        setUiDraft(
                          active.ui ? JSON.stringify(active.ui, null, 2) : "{}",
                        );
                      }}
                    >
                      Reset to manifest
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
