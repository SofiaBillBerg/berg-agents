"use client";

import { useEffect } from "react";

import ErrorBoundary from "./components/ErrorBoundary.tsx";
import App from "./App.tsx";

/**
 * ClientOnly wrapper component.
 * Sets up client-side error listeners and mounts the main App interface.
 */
export function ClientOnly() {
  useEffect(() => {
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

  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}
