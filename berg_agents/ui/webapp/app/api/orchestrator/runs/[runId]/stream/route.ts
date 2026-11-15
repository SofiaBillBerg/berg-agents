import {createUIMessageStreamResponse, type UIMessage} from "ai";
import {createModelCallToUIChunkTransform} from "@ai-sdk/workflow";
import {getRun} from "workflow/api";

/**
 * Replay one past orchestration, chunk for chunk, as it was recorded.
 *
 * The same construction the conversation route uses to answer a turn — a run's
 * durable readable stream, piped through the SDK's own chunk transform — pointed
 * at a run that already finished instead of one that just started. That
 * identity is deliberate: restoring is reading the same bytes the turn wrote,
 * not a rebuilt approximation of them.
 *
 * It is a filesystem route, like its siblings: an orchestration is a TS
 * workflow run, so its stream lives in berg's own workflow world rather than in
 * anything Python serves.
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
    let run;
    try {
        run = getRun<UIMessage[]>(runId);
    } catch {
        // An unknown id is the caller's mistake, not berg's failure: say so
        // plainly rather than streaming an error mid-response.
        return new Response("unknown run", {status: 404});
    }

    return createUIMessageStreamResponse({
        stream: run.readable.pipeThrough(createModelCallToUIChunkTransform()),
        // The id is carried so a client that is adopting this run as its own
        // conversation can address the next turn to it.
        headers: {"x-workflow-run-id": runId}});
}