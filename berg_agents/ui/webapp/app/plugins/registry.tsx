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
 * Plugin UI registry — the host's only knowledge of plugin surfaces.
 *
 * Plugins declare their own component in `plugin.yaml` (`ui:` block)
 * and ship a BUIL bundle in their package (`ui/dist/*.js`). The host
 * learns which plugins have surfaces from `GET /api/plugins` and
 * loads the plugin's bundle at runtime from `ui.entry_url` — it never
 * imports plugin source, so installing a plugin means no host edit
 * and no host rebuild.
 *
 * The bridge contract (what `/api/plugins` reports per plugin):
 *   ui.entry_url   - absolute URL of the plugin's built JS module
 *   ui.export      - named export mounting the component
 *   ui.entry_built - whether that file exists (false → explain why)
 *   ui.placement   - "side-panel" (docked) or "canvas"
 *   ui.label       - tool-bar label
 *   ui.width       - docked width in px
 */

"use client";

import type {ComponentType} from "react";

/** Props the host passes to any plugin surface. */
export interface PluginSurfaceProps {
    /** Side-panel (docked) or canvas (wide) presentation. */
    view: "panel" | "canvas";
    /** Bump to force a refetch (e.g. after an agent tool call). */
    refreshKey: number;
    /** Close the surface. */
    onClose?: () => void;
    /** Switch between panel and canvas views. */
    onToggleView?: () => void;
    /** Report a headline count for the host tool-bar badge. */
    onCount?: (n: number) => void;
    /** Layout classes from the host (e.g. width). */
    className?: string;
    /** Inline style from the host (e.g. manifest width). */
    style?: React.CSSProperties;
}

/** The UI declaration a plugin's manifest provides, as served. */
export interface PluginUIDeclaration {
    entry: string;
    export: string;
    entry_url?: string;
    entry_built?: boolean;
    placement?: string;
    label?: string;
    width?: number;
}

/** One loaded surface, ready to render. */
export interface LoadedPluginSurface {
    component: ComponentType<PluginSurfaceProps>;
}

/** Cache of already-imported bundles (module URL → named export). */
const loadedModules = new Map<string, Promise<unknown>>();

/**
 * Import a plugin's built bundle exactly once.
 *
 * `/* webpackIgnore: true *\/` keeps the host bundler from trying to
 * pre-bundle the plugin: the browser fetches it at runtime, which is
 * what makes the plugin independently shippable.
 *
 * @param entryUrl - Absolute URL of the plugin's built JS module.
 * @returns Promise of the module namespace object.
 */
function importPluginBundle(entryUrl: string): Promise<unknown> {
    const existing = loadedModules.get(entryUrl);
    if (existing) return existing;
    const pending = import(/* webpackIgnore: true */ entryUrl);
    loadedModules.set(entryUrl, pending);
    return pending;
}

/**
 * Load the component a plugin declares through its manifest.
 *
 * @param pluginId - Plugin id (for error messages).
 * @param ui - The `ui` descriptor from `/api/plugins`.
 * @returns The plugin's own component, or null when it cannot load
 *     (bundle missing, wrong export, or a load failure).
 */
export async function loadPluginSurface(
    pluginId: string,
    // Loose by design: this arrives as parsed JSON from /api/plugins, so
    // its shape is whatever the plugin's manifest declared.
    ui: Record<string, unknown> | PluginUIDeclaration | null | undefined,
): Promise<LoadedPluginSurface | null> {
    if (!ui || typeof ui.entry_url !== "string" || !ui.entry_url) {
        return null;
    }
    const exportName = typeof ui.export === "string" ? ui.export : "";
    if (!exportName) {
        return null;
    }
    try {
        const module = (await importPluginBundle(ui.entry_url)) as Record<
            string,
            unknown
        >;
        const component = module[exportName];
        if (typeof component !== "function") {
            console.error(
                `Plugin ${pluginId} bundle ${ui.entry_url} has no export "${exportName}".`,
            );
            return null;
        }
        return {component: component as ComponentType<PluginSurfaceProps>};
    } catch (error) {
        console.error(
            `Failed to load plugin UI bundle for ${pluginId} (${ui.entry_url}):`,
            error,
        );
        return null;
    }
}

/**
 * Tool names a plugin surface should refresh on, derived from the
 * plugin's own tool list — the host never enumerates them itself.
 *
 * @param tools - Tool names reported for the plugin.
 * @returns The same list as a Set.
 */
export function pluginRefreshTools(tools: string[] | undefined): Set<string> {
    return new Set(tools ?? []);
}
