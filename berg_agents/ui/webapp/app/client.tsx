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

import { Suspense, useEffect, useState } from "react";

import ErrorBoundary from "./components/ErrorBoundary.tsx";
import App from "./App.tsx";
import { installBergRuntime } from "./runtime/berg-runtime.ts";

/**
 * ClientOnly wrapper component.
 * Sets up client-side error listeners and mounts the main App interface.
 *
 * Defers the first render until after mount: AI SDK's `useChat` generates
 * random message IDs during render, which must never run during SSR /
 * prerender (Next.js `blocking-prerender-random-client`) and would
 * otherwise also cause hydration mismatches. Rendering `null` on the
 * server and on the very first client pass keeps server and client HTML
 * identical.
 */
export function ClientOnly() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Plugin UI bundles resolve React/HeroUI against this runtime, so
    // it must exist before any plugin surface is imported.
    installBergRuntime();
    // Global uncaught error handler for frontend debugging
    const handleError = (event: ErrorEvent) => {
      console.error("Global UI error:", event.error);
    };

    const handleRejection = (event: PromiseRejectionEvent) => {
      console.error("Unhandled promise rejection:", event.reason);
    };

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);

    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  if (!mounted) {
    return <div className="p-8 text-sm">Loading chat...</div>;
  }

  return (
    <ErrorBoundary>
      <Suspense fallback={<div className="p-8 text-sm">Loading chat...</div>}>
        <App />
      </Suspense>
    </ErrorBoundary>
  );
}
