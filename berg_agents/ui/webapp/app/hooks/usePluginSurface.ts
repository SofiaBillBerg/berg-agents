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

/*
 * Plugin surfaces (side-panel + canvas views), driven entirely by
 * what the plugins declare in their manifests. The host holds no
 * knowledge of any plugin's domain: it learns "this plugin has a
 * surface, here is how to mount it" from GET /api/plugins.
 *
 * It is a machine of its own - which surface is open, how it is
 * presented, how wide, and when it must re-fetch - so it lives as a hook
 * rather than eight `useState`s in the layout component. Moved
 * byte-identical: only the API base became a dependency and the dead
 * `activeLabel` (derived, never rendered) was dropped.
 */

import type {ChatMessage} from "@/harness";

import {useCallback, useEffect, useRef, useState} from "react";

import {fetchPlugins} from "@/lib/backendCatalog";


/** What the hook needs from the layout component. */
export interface UsePluginSurfaceDeps {
    /** Base URL of the Berg Agents API. */
    apiBase: string;
    /** The live transcript: completed tool calls refresh an open surface. */
    messages: readonly ChatMessage[];
}

/** One plugin that declared a UI surface. */
export interface PluginSurfaceEntry {
    pluginId: string;
    ui: Record<string, unknown> | null;
    tools: string[];
}

/** The surface machine's state and its two actions. */
export interface PluginSurface {
    /** Plugin id whose surface is open, or the catalog. */
    sidePluginId: string | null;
    setSidePluginId: React.Dispatch<React.SetStateAction<string | null>>;
    /** Show the host's plugin catalog (enable/disable, no plugin UI). */
    showCatalog: boolean;
    setShowCatalog: React.Dispatch<React.SetStateAction<boolean>>;
    /** Panel (narrow) vs canvas (wide) presentation. */
    pluginView: "panel" | "canvas";
    setPluginView: React.Dispatch<React.SetStateAction<"panel" | "canvas">>;
    /** Width (px) of the docked side surface. */
    sideWidth: number;
    /** The surface's width setter (the close path resets it). */
    setSideWidth: React.Dispatch<React.SetStateAction<number>>;
    /** True while the divider is being dragged (drives the cursor). */
    sideDragging: boolean;
    /** Begin a divider drag (pointer capture). */
    startSideDrag: (e: React.PointerEvent) => void;
    /** Registry entries for plugins that shipped a surface. */
    pluginSurfaces: PluginSurfaceEntry[];
    /** The open surface's entry, when one is open. */
    activeSurface: PluginSurfaceEntry | undefined;
    /** Bump to force the open surface to refetch after agent calls. */
    pluginRefreshKey: number;
    /** Headline count reported by the open surface (badge). */
    pluginCount: number;
    setPluginCount: React.Dispatch<React.SetStateAction<number>>;
}

/**
 * Own the plugin surface machine.
 *
 * @param deps - The API base and the live transcript.
 * @returns The machine's state and its drag/refresh actions.
 */
export function usePluginSurface(deps: UsePluginSurfaceDeps): PluginSurface {
    const {apiBase, messages} = deps;

    const [sidePluginId, setSidePluginId] = useState<string | null>(null);
    const [showCatalog, setShowCatalog] = useState(false);
    const [pluginView, setPluginView] = useState<"panel" | "canvas">("panel");
    /**
     * Width (px) of the docked side surface. Draggable via the handle
     * between the transcript and the surface — the fixed 340px clipped
     * the MCP/skill descriptions so toggles were unreadable.
     */
    const [sideWidth, setSideWidth] = useState(340);
    /** True while the divider is being dragged (drives the cursor). */
    const [sideDragging, setSideDragging] = useState(false);
    /** Bump to force the open surface to refetch after agent calls. */
    const [pluginRefreshKey, setPluginRefreshKey] = useState(0);
    /** Headline count reported by the open surface (badge). */
    const [pluginCount, setPluginCount] = useState(0);
    /** Registry entries for plugins that shipped a surface. */
    const [pluginSurfaces, setPluginSurfaces] = useState<PluginSurfaceEntry[]>(
        [],
    );

    // Discover which plugins have a registered surface.
    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            const plugins = await fetchPlugins();
            if (cancelled) return;
            const found: PluginSurfaceEntry[] = [];
            for (const p of plugins) {
                if (!p || typeof p.id !== "string" || !p.ui) continue;
                // NOTE: the manifest is the only filter — any plugin that
                // declares a `ui:` block is offered. Whether its bundle loads
                // is the bridge's problem, reported on the surface itself.
                found.push({
                    pluginId: p.id,
                    ui: p.ui as Record<string, unknown> | null,
                    tools: Array.isArray(p.tools) ? (p.tools as string[]) : []});
            }
            setPluginSurfaces(found);
        };
        void load();
        return () => {
            cancelled = true;
        };
         
    }, []);

    const activeSurface = pluginSurfaces.find((s) => s.pluginId === sidePluginId);

    // Completed tool calls anywhere in the transcript refresh the open
    // surface, so agent edits appear without manual reloads.
    const activeTools =
        pluginSurfaces.find((s) => s.pluginId === sidePluginId)?.tools ?? [];
    const pluginActivity = messages.reduce(
        (n, m) =>
            n +
            (m.toolCalls?.filter((c) => activeTools.includes(c.tool)).length ?? 0),
        0,
    );
    const seenPluginActivity = useRef(0);
    useEffect(() => {
        if (pluginActivity > seenPluginActivity.current) {
            seenPluginActivity.current = pluginActivity;
            setPluginRefreshKey((k) => k + 1);
        }
    }, [pluginActivity]);

    // -------------------------------------------------------------------------
    // Side-surface resize: pointer-capture divider between the transcript
    // and the docked surface. Width is clamped so the transcript always
    // keeps a usable column, and reset when the surface closes.
    // -------------------------------------------------------------------------
    const sideDragStart = useRef<{ x: number; w: number } | null>(null);

    const onSideDragMove = useCallback((e: PointerEvent) => {
        const start = sideDragStart.current;
        if (!start) return;
        // Dragging left grows the surface (it sits to the right of the
        // divider), so the delta is inverted.
        const next = start.w - (e.clientX - start.x);
        const max = Math.max(320, window.innerWidth - 420);
        setSideWidth(Math.min(max, Math.max(280, next)));
    }, []);

    const onSideDragEnd = useCallback(() => {
        sideDragStart.current = null;
        setSideDragging(false);
    }, []);

    useEffect(() => {
        if (!sideDragging) return;
        window.addEventListener("pointermove", onSideDragMove);
        window.addEventListener("pointerup", onSideDragEnd);
        return () => {
            window.removeEventListener("pointermove", onSideDragMove);
            window.removeEventListener("pointerup", onSideDragEnd);
        };
    }, [sideDragging, onSideDragMove, onSideDragEnd]);

    const startSideDrag = (e: React.PointerEvent) => {
        sideDragStart.current = {x: e.clientX, w: sideWidth};
        setSideDragging(true);
    };

    return {
        sidePluginId,
        setSidePluginId,
        showCatalog,
        setShowCatalog,
        pluginView,
        setPluginView,
        sideWidth,
        setSideWidth,
        sideDragging,
        startSideDrag,
        pluginSurfaces,
        activeSurface,
        pluginRefreshKey,
        pluginCount,
        setPluginCount};
}
