import {createUIMessageStreamResponse, type UIMessage} from "ai";
import {createModelCallToUIChunkTransform} from "@ai-sdk/workflow";
import {getRun} from "workflow/api";

/**
 * Replay one past orchestration, chunk for chunk, as it was recorded.
 *
 * The same construction the conversation route uses to answer a turn — a run's
 * durable readable stream, piped through the SDK's own chunk transform —
 * pointed at a run that already finished instead of one that just started.
 * That identity is deliberate: restoring reads the bytes the turn actually
 * wrote, not a rebuilt approximation of them.
 *
 * Why this lives OUTSIDE `/api/*`, where its sibling list route lives:
 * measured on 2026-11-15, a dynamic API segment under `/api/orchestrator/…`
 * never reaches its handler — the `/api/:path*` rewrite claims the request
 * first, even though `routes-manifest.json` lists the route as dynamic and the
 * rewrite is `afterFiles`. A trivial probe route (`/api/orchestrator/pingx/[id]`)
 * behaved identically, so it is the pattern, not this file. Static segments
 * under the same prefix are served normally. Keeping the replay outside `/api`
 * sidesteps that instead of guessing at Next's matcher; if a future Next
 * version fixes the precedence, this can move under `/api` and stay equivalent.
 *
 * @param request - The incoming request.
 * @param context - The route context, carrying the run id from the path.
 * @returns The run's UI message chunks, or 404 when that run is unknown.
 */
export async function GET(
    request: Request,
    {params}: {params: Promise<{runId: string}>},
): Promise<Response> {
    const {runId} = await params;
    const run = getRun<UIMessage[]>(runId);

    // An unknown id is the caller's mistake, not berg's failure. `getRun`
    // does not raise for one — it hands back a run whose readable stream never
    // completes — so the existence check has to be explicit, or a bad id hangs
    // the client instead of answering 404.
    if (!(await run.exists)) {
        return new Response("unknown run", {status: 404});
    }

    // `startIndex` is the resume contract the SDK's own transport speaks
    // (`?startIndex=0` replays from the beginning): honour it so a client that
    // already consumed part of a run can ask for the rest. `readable` is a
    // property holding the default stream; `getReadable(options)` is the
    // options-taking form, so the whole stream is only asked for when no index
    // was given.
    const startIndex = Number(new URL(request.url).searchParams.get("startIndex"));
    const readable =
        Number.isInteger(startIndex) && startIndex >= 0
            ? run.getReadable({startIndex})
            : run.readable;

    return createUIMessageStreamResponse({
        stream: readable.pipeThrough(createModelCallToUIChunkTransform()),
        // Carried so a client that adopts this run as its own conversation can
        // address the next turn to it.
        headers: {"x-workflow-run-id": runId}});
}