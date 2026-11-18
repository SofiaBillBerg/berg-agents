import { listTurns } from "@/lib/orchestrator-turns";

/**
 * Past orchestrator runs, newest first.
 *
 * Reads berg's own conversation store (lib/orchestrator-turns.ts), joined
 * against the workflow world's runs for live status. The world alone was not
 * enough: it is the agent's log, so a run it lists has no conversation attached
 * — and it would list every run ever started, including ones Sofia never
 * conversed in. What belongs in her list is what she can restore or delete.
 *
 * A filesystem route rather than a proxied one, because an orchestration run is
 * a TS workflow run: its record lives in the workflow world's PostgreSQL (the
 * tables under the `workflow` schema, not in berg's Python sessions), which is
 * why no orchestrator run ever appeared in the History tab.
 */
export async function GET(): Promise<Response> {
  const runs = await listTurns();
  return Response.json({ runs });
}
