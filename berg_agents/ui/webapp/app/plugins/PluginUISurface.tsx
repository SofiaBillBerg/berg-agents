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

import {useEffect, useState} from "react";
import {Card, Spinner} from "@heroui/react";

import type {PluginSurfaceProps} from "./registry.tsx";
import {loadPluginSurface} from "./registry.tsx";

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
  const [component, setComponent] = useState<
    PluginSurfaceProps extends never ? never : unknown
  >(null);
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
        const declared = (ui as {entry?: unknown} | null)?.entry;
        const built = (ui as {entry_built?: unknown} | null)?.entry_built;
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
