import { createUIMessageStreamResponse, type UIMessage } from "ai";
import { createModelCallToUIChunkTransform } from "@ai-sdk/workflow";
import { getRun } from "workflow/api";

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
 * sidesteps that instead of guessing at Next.js matcher; if a future Next
 * version fixes the precedence, this can move under `/api` and stay equivalent.
 *
 * @param request - The incoming request.
 * @param context - The route context, carrying the run id from the path.
 * @returns The run's UI message chunks, or 404 when that run is unknown.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
): Promise<Response> {
  const { runId } = await params;
  const run = getRun<UIMessage[]>(runId);

  // An unknown id is the caller's mistake, not berg's failure. `getRun`
  // does not raise for one — it hands back a run whose readable stream never
  // completes — so the existence check has to be explicit, or a bad id hangs
  // the client instead of answering 404.
  if (!(await run.exists)) {
    return new Response("unknown run", { status: 404 });
  }

  // The resume contract `WorkflowChatTransport` speaks: a client that already
  // consumed part of a run asks for the rest by UI cursor. 0 means "replay it
  // all", which is what restoring a past run into a fresh page wants.
  const startIndex = Number(
    new URL(request.url).searchParams.get("startIndex") ?? "0",
  );
  if (!Number.isSafeInteger(startIndex) || startIndex < 0) {
    return Response.json(
      { error: "startIndex must be a non-negative safe integer" },
      { status: 400 },
    );
  }

  // The durable stream holds raw `ModelCallStreamPart` objects while the
  // client speaks `UIMessageChunk`, so the raw stream is replayed from index 0
  // and the UI cursor is applied inside the transform. Replaying the raw
  // stream *from* startIndex would skip raw chunks the UI cursor has not
  // reached yet: the two index spaces are not interchangeable.
  // The durable stream holds raw `ModelCallStreamPart` objects while the client
  // speaks `UIMessageChunk`, so the raw stream is replayed from index 0 and the
  // UI cursor is applied inside the transform. Replaying the raw stream *from*
  // startIndex would skip raw chunks the UI cursor has not reached yet: the two
  // index spaces are not interchangeable.
  //
  // Known limit, recorded rather than papered over: a turn whose model step
  // retried can leave the recorded stream holding a tool's OUTPUT with no
  // matching INPUT chunks (measured on the run that was cut off mid-turn on
  // 2026-11-14: 474 chunks, 3 tool outputs, 2 tool inputs). A live turn repairs
  // that with the `reset-step` the transform forwards; on replay the client's
  // accumulator reports "No tool invocation found for tool call ID" and the
  // restored transcript shows that line. `normalizeUIMessageStreamParts` does
  // NOT close this hole (tried), so the next place to look is what a retried
  // step owes the durable stream.
  const readable = run
    .getReadable({ startIndex: 0 })
    .pipeThrough(
      createModelCallToUIChunkTransform({ uiStartIndex: startIndex }),
    );

  return createUIMessageStreamResponse({
    stream: readable,
    // Carried so a client that adopts this run as its own conversation can
    // address the next turn to it.
    headers: { "x-workflow-run-id": runId }});
}
