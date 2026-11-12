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

/**
 * PluginUISurface — renders whichever plugin surface is active.
 *
 * The host holds no knowledge of what a plugin does: it reads the
 * `ui:` block from `/api/plugins`, loads the plugin's own built bundle
 * at runtime, and mounts the component the manifest names. A plugin
 * whose bundle is not built, or fails to load, renders an honest note
 * instead of an empty panel.
 */

"use client";

import type { PluginSurfaceProps } from "./registry.tsx";

import { useEffect, useState } from "react";
import { Card, Spinner } from "@heroui/react";

import { loadPluginSurface } from "./registry.tsx";

export interface PluginUISurfaceProps extends PluginSurfaceProps {
  /** Plugin id to render (from `/api/plugins`). */
  pluginId: string;
  /** Declared `ui:` block from the plugin manifest. */
  ui?: Record<string, unknown> | null;
}

/** PluginUISurface - one plugin's own UI, loaded and mounted by the host. */
export function PluginUISurface({
  pluginId,
  ui,
  ...rest
}: PluginUISurfaceProps) {
  const [component, setComponent] =
    useState<PluginSurfaceProps extends never ? never : unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void loadPluginSurface(pluginId, ui).then((loaded) => {
      if (cancelled) return;
      if (loaded) {
        setComponent(() => loaded.component);
      } else {
        const declared = (ui as { entry?: unknown } | null)?.entry;
        const built = (ui as { entry_built?: unknown } | null)?.entry_built;
        setError(
          built === false && typeof declared === "string"
            ? `${pluginId} declares "${declared}", which has not been built. Run the plugin's build:ui script.`
            : `${pluginId} has no loadable UI surface in this build.`,
        );
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [pluginId, ui]);

  if (loading) {
    return (
      <Card className="mb-2 p-3" variant="default">
        <div className="flex items-center gap-2">
          <Spinner size="sm" />
          <span className="text-sm text-muted-foreground">
            Loading plugin UI…
          </span>
        </div>
      </Card>
    );
  }

  if (error || !component) {
    return (
      <Card className="mb-2 p-3" variant="default">
        <p className="text-sm font-medium">Plugin UI unavailable</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {error ?? `${pluginId} surface did not load.`}
        </p>
      </Card>
    );
  }

  const Surface = component as React.ComponentType<PluginSurfaceProps>;
  return <Surface {...rest} />;
}

export default PluginUISurface;
