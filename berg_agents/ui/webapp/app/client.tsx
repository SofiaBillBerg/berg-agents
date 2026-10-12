

"use client";

import {Suspense, useEffect, useState} from "react";

import ErrorBoundary from "./components/ErrorBoundary.tsx";
import App from "./App.tsx";

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
