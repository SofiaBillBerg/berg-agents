import {Client} from "pg";

/**
 * Past orchestrator runs, newest first.
 *
 * A filesystem route rather than a proxied one, because an orchestration run is
 * a TS workflow run: its record lives in the workflow world's PostgreSQL (the
 * tables under the `workflow` schema, not in berg's Python sessions), which is
 * why no orchestrator run ever appeared in the History tab.
 *
 * The connection URL is the world's own — `workflow-data-dir.mjs` sets it before
 * the workflow plugin loads — so there is no second destination to configure.
 * `pg` is resolvable here only as a transitive dependency of
 * `@workflow/world-postgres`; that coupling is named rather than left to be
 * discovered, because a dependency change would break this route at runtime.
 *
 * Only plain columns are read. A run's *conversation* is not among them: the
 * payload columns are zstd-compressed CBOR (see
 * `.opencode/plans/orchestrator-ux-plan.md`), which is why restoring a run needs
 * its own route rather than a column here.
 */
export async function GET(): Promise<Response> {
    const url = process.env.WORKFLOW_POSTGRES_URL;
    if (!url) {
        return Response.json({
            runs: [],
            detail: "no workflow world: WORKFLOW_POSTGRES_URL is unset"});
    }

    const client = new Client({connectionString: url});
    try {
        await client.connect();
        const result = await client.query(
            `SELECT id, status, created_at, completed_at
               FROM workflow.workflow_runs
              WHERE name LIKE '%orchestrator-turn%'
              ORDER BY created_at DESC
              LIMIT 50`,
        );
        return Response.json({runs: result.rows});
    } finally {
        // Always released: a route that leaks a client holds a backend
        // connection per request, and this runs on every page open.
        await client.end().catch(() => undefined);
    }
}