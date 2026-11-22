/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * Deliver one payload to an orchestrator session.
 *
 * This is the door the whole session refactor turns on. The old shape re-sent
 * the conversation to POST /api/orchestrator, which STARTED A NEW RUN — so an
 * approval answer launched a sibling session and the next turn re-planned from
 * the client's view of the past. Here the same run is resumed by the run id in
 * the path: the workflow is suspended on its hook, this resumes that hook, and
 * the run continues with its OWN history, its OWN tool results, and the same
 * run id. That is the "Message injection: resume a Hook" column of the SDK's
 * chat-session guide, and it is what the world's tables were missing — 74
 * orchestrator runs and zero hooks.
 *
 * Why this lives OUTSIDE `/api`: a dynamic segment under the proxied prefix
 * never reaches its handler — `/api/:path*` claims the request first, and
 * `routes-manifest.json` listing the route as dynamic does not change that
 * (measured 2026-11-15, recorded at `app/orchestrator/[runId]/stream/route.ts`).
 */

import {
  orchestratorSessionHook,
  orchestratorSessionInput} from "@/workflows/orchestrator-turn";

/**
 * POST /orchestrator/<runId>/message
 *
 * @param request - JSON body: `{kind:"message", text}`, `{kind:"approval",
 *   approvalId, approved, reason?}`, or `{kind:"done"}`.
 * @param context - The route context, carrying the run id from the path.
 * @returns Success, 400 for a body the schema refuses, or 404 when that run
 *   holds no waiting session.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
): Promise<Response> {
  const { runId } = await params;
  const parsed = orchestratorSessionInput.safeParse(
    await request.json().catch(() => null),
  );
  if (!parsed.success) {
    // The hook validates again on resume; this check exists so a malformed
    // body answers 400 with its reason rather than throwing out of the SDK.
    return Response.json(
      { error: "body must be a message, an approval, or done" },
      { status: 400 },
    );
  }

  try {
    await orchestratorSessionHook.resume(runId, parsed.data);
  } catch (error) {
    // No waiting session: the run finished, was stopped, or the id is simply
    // wrong. Say so rather than reporting a success that changes nothing —
    // the client's answer would be dropped on the floor otherwise.
    return Response.json(
      {
        error: error instanceof Error ? error.message : "no session resumed"},
      { status: 404 },
    );
  }

  return Response.json({ success: true, runId });
}
