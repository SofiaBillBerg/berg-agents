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
 * Host runtime shared with plugin UI bundles.
 *
 * Plugin bundles (built by each plugin's own `build:ui`) import React
 * and component libraries as EXTERNALS resolved against
 * `window.BergRuntime`. Exposing the host's own instances here is what
 * guarantees a single React: a plugin cannot ship a second copy, so
 * hooks, context, and HeroUI state keep working across the boundary.
 *
 * `require(specifier)` is the plugin-facing resolver; it returns the
 * host's own module object for the specifier the plugin imported.
 */

"use client";

import * as React from "react";
import * as ReactJSXRuntime from "react/jsx-runtime";
import * as ReactDOM from "react-dom";
import * as ReactDOMClient from "react-dom/client";
import * as HeroUI from "@heroui/react";

import {API_BASE} from "@/envConfig";

/** Modules a plugin bundle may resolve through the runtime. */
const RUNTIME_MODULES: Record<string, unknown> = {
    react: React,
    "react/jsx-runtime": ReactJSXRuntime,
    "react/jsx-dev-runtime": ReactJSXRuntime,
    "react-dom": ReactDOM,
    "react-dom/client": ReactDOMClient,
    "@heroui/react": HeroUI};

interface BergRuntimeGlobal {
    React: typeof React;
    HeroUI: typeof HeroUI;
    /**
     * API base the host itself uses (empty means same-origin). Published
     * so plugin bundles follow the host's backend instead of a value
     * frozen into the plugin at its own build time.
     */
    apiBase: string;
    /** Resolve a bare specifier to the host's own module object. */
    require: (specifier: string) => unknown;
}

declare global {
    interface Window {
        BergRuntime?: BergRuntimeGlobal;
    }
}

/**
 * Install the runtime on `window` exactly once.
 *
 * Idempotent: a second call (React strict-mode double-invoke, hot
 * reload) reuses the existing object rather than replacing it, so
 * already-loaded plugin bundles keep their references.
 */
export function installBergRuntime(): void {
    if (typeof window === "undefined" || window.BergRuntime) return;
    window.BergRuntime = {
        React,
        HeroUI,
        apiBase: API_BASE,
        require: (specifier: string) => {
            const mod = RUNTIME_MODULES[specifier];
            if (mod === undefined) {
                throw new Error(
                    `Plugin UI imported "${specifier}", which the host runtime does ` +
                    `not expose. Add it to RUNTIME_MODULES in ` +
                    `app/runtime/berg-runtime.ts.`,
                );
            }
            return mod;
        }};
}
