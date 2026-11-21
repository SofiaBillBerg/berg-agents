/*
 * The route into one specialist's session.
 *
 * A server component on purpose: it is the shell that renders on demand
 * and hands the live surface to the browser. The `params` promise is
 * passed THROUGH to the client view rather than unwrapped here, because
 * the run id is what makes this route dynamic — unwrapping it inside the
 * Suspense boundary (as Next's streaming guidance prescribes) lets the
 * shell prerender and the session arrive without the route blocking:
 * https://nextjs.org/docs/app/guides/streaming
 */

import { Suspense } from "react";

import SpecialistSessionView from "./session-view";

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
  // The placeholder is a real state, not a spinner: the stream is adopted
  // and replayed in the client, so the shell paints immediately and the
  // turn's history arrives as one piece.
  return (
    <Suspense
      fallback={
        <main className="p-6 text-sm text-muted-foreground">
          Opening the specialist&rsquo;s session…
        </main>
      }
    >
      <SpecialistSessionView params={params} />
    </Suspense>
  );
}
