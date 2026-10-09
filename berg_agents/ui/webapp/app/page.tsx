/**
 * Main landing page for the Berg Agents web application.
 * Imports theme assets and renders the interactive client application.
 *
 * NOTE: do NOT add `export const dynamic = "force-dynamic"` here - the
 * project builds with `output: "export"` (static, mounted by FastAPI),
 * which requires every page to be statically prerenderable. The
 * `ClientOnly` wrapper below defers `useChat` (which uses `Math.random()`
 * internally) until after mount, so prerendering only ever sees the
 * deterministic "Loading chat..." fallback.
 */

import { Suspense } from "react";

import { ClientOnly } from "./client.tsx";

/**
 * Root Page component for Next.js App Router.
 *
 * @returns JSX element rendering the client-only application.
 */
export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-sm">Loading chat...</div>}>
      <ClientOnly />
    </Suspense>
  );
}
