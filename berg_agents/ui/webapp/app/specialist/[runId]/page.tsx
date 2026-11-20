/*
 * The route into one specialist's session.
 *
 * A server component on purpose: `export const instant` is a route segment
 * config and Next accepts it only from a Server Component module. The live
 * surface (stream, polling, actions) is the client view this renders, so the
 * split is the documented one rather than a workaround.
 */

import { Suspense, use } from "react";

import SpecialistSessionView from "./session-view";

/**
 * The route shell: the run id from the URL, and the live session it names.
 *
 * A blocking route by intent — this page is one live specialist run, and every
 * read on it (the durable stream, the run's state) is uncached and per-run, so
 * Next's guidance is to say that outright rather than let prerender block on
 * data that can never be cached
 * (https://nextjs.org/docs/messages/blocking-prerender-dynamic).
 */
export const instant = false;

/**
 * Render one specialist's session.
 *
 * @param props - The route's params: the run id.
 * @returns The specialist's session surface.
 */
export default function SpecialistSessionPage({
  params}: {
  params: Promise<{ runId: string }>;
}) {
  // `params` is a Promise in this Next version (per its own route docs), so
  // unwrapping it is the documented `use` rather than an await.
  const { runId } = use(params);
  // The placeholder is a real state, not a spinner: the stream is adopted
  // and replayed in the client, and this route renders on demand — so the
  // shell paints immediately and the turn's history arrives as one piece.
  return (
    <Suspense
      fallback={
        <main className="p-6 text-sm text-muted-foreground">
          Opening the specialist&rsquo;s session…
        </main>
      }
    >
      <SpecialistSessionView runId={runId} />
    </Suspense>
  );
}
