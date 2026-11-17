import {Client} from "pg";

/**
 * The orchestrator's own conversation store.
 *
 * Why it exists: a workflow run's durable stream records what the AGENT wrote,
 * not what the user said. Restoring from that stream alone produces a transcript
 * missing the user's own turns — which is exactly the half that makes a
 * `conversation` a conversation. The AI SDK's documented answer is to keep
 * `UIMessage[]` as the source of truth (there is no reverse conversion from what
 * a run records), so the turn boundary writes the messages here, keyed by the
 * run it started.
 *
 * Durable on purpose: these rows live in
 * berg's own PostgreSQL rather than in browser memory that a reload clears.
 *
 * The connection is the workflow world's (set by `workflow-data-dir.mjs` before
 * the plugin loads), but the table is berg's own, in its own schema — berg owns
 * its data, and it does not write into the SDK's `workflow` schema.
 */

/** The schema berg's own tables live in, inside the world's database. */
const BERG_SCHEMA = "berg";

/** The table holding one conversation per orchestrator run. */
const TURNS_TABLE = `${BERG_SCHEMA}.orchestrator_turns`;

/**
 * The table recording runs removed from the list.
 *
 * Delete has to mean "gone on the next reload too", and the union in
 * listTurns is what breaks that: the workflow world lists EVERY run, so a
 * run whose berg row was deleted simply reappears through the world's
 * branch (she deleted 15 rows and watched the panel return to 50). A
 * tombstone closes that hole without touching the world's own record —
 * the run's event log stays exactly as it was, and only berg's list stops
 * showing it.
 */
const DELETED_TABLE = `${BERG_SCHEMA}.orchestrator_turns_deleted`;

/**
 * Create berg's table if it is missing.
 *
 * Idempotent, and safe to run on every boot: the alternative is a migration
 * framework for one table, and the cost of `IF NOT EXISTS` is nothing.
 *
 * @param client - An open connection to the world's database.
 */
async function ensureTable(client: Client): Promise<void> {
    await client.query(`CREATE SCHEMA IF NOT EXISTS ${BERG_SCHEMA}`);
    await client.query(`
        CREATE TABLE IF NOT EXISTS ${TURNS_TABLE} (
            run_id      text PRIMARY KEY,
            messages    jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    `);
    await client.query(`
        CREATE TABLE IF NOT EXISTS ${DELETED_TABLE} (
            run_id      text PRIMARY KEY,
            deleted_at  timestamptz NOT NULL DEFAULT now()
        )
    `);
}

/**
 * Open a connection with berg's table guaranteed to exist.
 *
 * @returns A connected client, or null when no workflow world is configured.
 */
async function connect(): Promise<Client | null> {
    const url = process.env.WORKFLOW_POSTGRES_URL;
    if (!url) return null;
    const client = new Client({connectionString: url});
    await client.connect();
    await ensureTable(client);
    return client;
}

/**
 * Record the conversation a run started with.
 *
 * @param runId - The run the turn became.
 * @param messages - The conversation as the UI holds it, at the moment the turn
 *   was sent: everything the user and the orchestrator had said so far.
 */
export async function saveTurn(
    runId: string,
    messages: unknown,
): Promise<void> {
    const client = await connect();
    if (!client) return;
    try {
        // ON CONFLICT, not INSERT OR REPLACE: a run id identifies one turn, so
        // a second write for the same id is a correction of that same turn
        // rather than a second row pretending a second turn happened.
        await client.query(
            `INSERT INTO ${TURNS_TABLE} (run_id, messages)
             VALUES ($1, $2)
             ON CONFLICT (run_id) DO UPDATE SET messages = EXCLUDED.messages`,
            [runId, JSON.stringify(messages)],
        );
    } finally {
        await client.end().catch(() => undefined);
    }
}

/** One past turn, as the list shows it. */
export interface StoredTurn {
    /** The run id — the handle for restoring or deleting it. */
    runId: string;
    /** What the run is doing now, from the workflow world's own record. */
    status: string;
    /** When the turn was sent. */
    createdAt: string | null;
    /**
     * Whether berg holds the conversation for this run.
     *
     * False for turns started before the store existed: the world still has the
     * agent's log (so the run can be replayed from its stream) but there is no
     * conversation of Sofia's to restore or delete. The flag is what lets the
     * page offer restore-without-conversation and drop the delete button,
     * rather than offering a delete that would remove nothing of hers.
     */
    hasConversation: boolean;
}

/**
 * The turns berg has recorded, newest first.
 *
 * Two sources, one list, because they answer different halves of "what did we
 * do together":
 *
 * - berg's store: the conversation, so a run can be restored with both sides and
 *   deleted — but it only holds turns sent since it existed.
 * - the workflow world: every orchestration run ever started, which is the
 *   agent's own log. Reading only berg's store made that history disappear from
 *   the page the day the store arrived (found 2026-11-15 from a screenshot: a
 *   panel that used to list 29 runs listed none), which is the regression this
 *   union repairs.
 *
 * The world's rows come second, and only where berg has no conversation of its
 * own, so nothing is listed twice. Runs Sofia deleted are excluded from both
 * branches: a tombstone (DELETED_TABLE) is what "delete" leaves behind, so a
 * deleted run cannot reappear through the world's branch on the next load.
 *
 * @returns The stored turns, newest first.
 */
export async function listTurns(): Promise<StoredTurn[]> {
    const client = await connect();
    if (!client) return [];
    try {
        // Each branch selects only columns its own table has: berg's table is
        // (run_id, messages, created_at) and carries no `status`, so the first
        // branch LEFT JOINs the world's run for it. Selecting `status` from
        // berg's table — which is what this query did first — is a parse error
        // ("column \"status\" does not exist"), and it took the whole panel down
        // rather than one row.
        const result = await client.query(
            `SELECT t.run_id, r.status, t.created_at, TRUE AS has_conversation
               FROM ${TURNS_TABLE} t
               LEFT JOIN workflow.workflow_runs r ON r.id = t.run_id
              UNION ALL
             SELECT r.id, r.status, r.created_at, FALSE
               FROM workflow.workflow_runs r
              WHERE r.name LIKE '%orchestrator-turn%'
                AND NOT EXISTS (
                    SELECT 1 FROM ${TURNS_TABLE} t WHERE t.run_id = r.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM ${DELETED_TABLE} d WHERE d.run_id = r.id
                )
              ORDER BY created_at DESC
              LIMIT 50`,
        );
        return result.rows.map((row) => ({
            runId: String(row.run_id),
            status: String(row.status ?? "unknown"),
            createdAt: row.created_at ? String(row.created_at) : null,
            hasConversation: Boolean(row.has_conversation)}));
    } finally {
        await client.end().catch(() => undefined);
    }
}

/**
 * The conversation a run started with, for restoring it.
 *
 * @param runId - The run to restore.
 * @returns The stored messages, or null when berg has no record of that turn.
 */
export async function loadTurn(
    runId: string,
): Promise<unknown[] | null> {
    const client = await connect();
    if (!client) return null;
    try {
        const result = await client.query(
            `SELECT messages FROM ${TURNS_TABLE} WHERE run_id = $1`,
            [runId],
        );
        if (result.rowCount === 0) return null;
        const stored = result.rows[0]?.messages;
        return Array.isArray(stored) ? stored : null;
    } finally {
        await client.end().catch(() => undefined);
    }
}

/**
 * Delete one turn's conversation.
 *
 * By id, one run, because deleting a conversation is Sofia's decision and a
 * wildcard or a bulk path would make it anyone else's. Two writes, in
 * berg's own tables only: the conversation row goes, and a tombstone records
 * that this run is to stay out of the list — without it the union's second
 * branch would re-list the run through the workflow world on the next load,
 * which is the "delete did nothing" this replaces. The world's event log is
 * the run's record of what the agent did, and it stays: emptying her list
 * must not rewrite history she did not ask to lose.
 *
 * Idempotent: deleting an already-deleted run confirms rather than 404s, so
 * the second click on a stale row is not an error.
 *
 * @param runId - The run whose conversation should be deleted.
 * @returns True once the run is out of the list.
 */
export async function deleteTurn(runId: string): Promise<boolean> {
    const client = await connect();
    if (!client) return false;
    try {
        await client.query(
            `DELETE FROM ${TURNS_TABLE} WHERE run_id = $1`,
            [runId],
        );
        await client.query(
            `INSERT INTO ${DELETED_TABLE} (run_id)
             VALUES ($1)
             ON CONFLICT (run_id) DO NOTHING`,
            [runId],
        );
        return true;
    } finally {
        await client.end().catch(() => undefined);
    }
}
