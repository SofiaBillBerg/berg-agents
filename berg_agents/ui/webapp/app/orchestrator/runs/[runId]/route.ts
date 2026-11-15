import {deleteTurn, loadTurn, saveTurn} from "@/lib/orchestrator-turns";

/**
 * One past orchestration: read its conversation back, record what it ended with,
 * or delete it.
 *
 * Outside `/api/*` for the reason measured on 2026-11-15: a DYNAMIC API segment
 * under `/api/…` is claimed by the `/api/:path*` rewrite before its handler runs
 * (a probe route beside the working static ones behaved identically), so berg's
 * per-run routes live here instead and the rewrite never sees them.
 *
 * @param request - The incoming request.
 * @param context - The route context, carrying the run id from the path.
 * @returns The stored conversation, 204 when it is deleted, or 404 when berg has
 *   no record of that run.
 */
export async function GET(
    request: Request,
    {params}: {params: Promise<{runId: string}>},
): Promise<Response> {
    const {runId} = await params;
    const messages = await loadTurn(runId);
    if (messages === null) {
        // Not recorded, rather than unknown: the run may exist in the workflow
        // world (it is the agent's log) while berg has no conversation for it —
        // which is the case for every turn sent before this store existed.
        return Response.json({detail: "no stored conversation"}, {status: 404});
    }
    return Response.json({runId, messages});
}

/**
 * Delete one turn's conversation.
 * A bulk or wildcard path would make a destructive act someone else's decision,
 * so there is none. The workflow world's record of what the agent did stays —
 * emptying her list must not rewrite history she did not ask to lose.
 *
 * @param request - The incoming request.
 * @param context - The route context, carrying the run id from the path.
 * @returns 204 when the row is gone, 404 when there was nothing to delete.
 */
/**
 * Record a turn's conversation once it is complete.
 *
 * The turn route writes the conversation a run STARTS with; this writes what it
 * ended with. Both matter: the start write means a turn is restorable the moment
 * it begins, and this one means the agent's replies land too — which the start
 * write cannot see, because they arrive on the stream rather than in the next
 * request. Same key, so this replaces that first row rather than adding a
 * second one (see saveTurn's ON CONFLICT).
 *
 * @param request - The incoming request, whose body carries the messages.
 * @param context - The route context, carrying the run id from the path.
 * @returns 204 once recorded.
 */
export async function POST(
    request: Request,
    {params}: {params: Promise<{runId: string}>},
): Promise<Response> {
    const {runId} = await params;
    const body = (await request.json()) as {messages?: unknown};
    await saveTurn(runId, body.messages ?? []);
    return new Response(null, {status: 204});
}

/**
 * Delete one turn's conversation.
 *
 * Deletes exactly what the path names: berg's copy of that one conversation.
 * A bulk or wildcard path would make a destructive act someone else's decision,
 * so there is none. The workflow world's record of what the agent did stays —
 * emptying her list must not rewrite history she did not ask to lose.
 *
 * @param request - The incoming request.
 * @param context - The route context, carrying the run id from the path.
 * @returns 204 when the row is gone, 404 when there was nothing to delete.
 */
export async function DELETE(
    request: Request,
    {params}: {params: Promise<{runId: string}>},
): Promise<Response> {
    const {runId} = await params;
    const deleted = await deleteTurn(runId);
    if (!deleted) {
        return Response.json({detail: "nothing to delete"}, {status: 404});
    }
    return new Response(null, {status: 204});
}