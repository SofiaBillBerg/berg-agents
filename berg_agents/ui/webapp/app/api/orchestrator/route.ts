/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * Start an orchestrator turn and stream it back in the UI's own protocol.
 *
 * Two conversions happen here and nowhere else, so the wire stays one wire:
 * `start` hands the turn to the durable runtime, and
 * `createModelCallToUIChunkTransform` turns the runtime's raw model parts into
 * the `UIMessageChunk`s that berg's chat surface already renders.
 */

import {createModelCallToUIChunkTransform} from "@ai-sdk/workflow";
import {createUIMessageStreamResponse, type UIMessage} from "ai";
import {start} from "workflow/api";

import {localModel} from "@/harness/local-model";
import {orchestratorTurn} from "@/workflows/orchestrator-turn";

/**
 * The orchestrator's model.
 *
 * `localModel` rather than a provider built here, because a `WorkflowAgent`
 * runs each model call as its own step and the model crosses that boundary as
 * data. The AI SDK's own providers serialize their config and lose `baseURL`
 * and the request `url` builder along the way (verified: both
 * `@ai-sdk/openai` and `@ai-sdk/openai-compatible` come back unable to make a
 * call), so the model has to carry plain strings and rebuild itself. berg's
 * endpoint is its own ollama — never a hosted gateway.
 *
 * @returns A model bound to berg's local endpoint, serializable across steps.
 */
function orchestratorModel() {
    return localModel();
}

/**
 * POST /api/orchestrator
 *
 * @param request - JSON body with `messages` (the UI's conversation).
 * @returns A UI message stream, and the run id for reconnection.
 */
export async function POST(request: Request): Promise<Response> {
    const body = (await request.json()) as { messages?: UIMessage[] };
    const messages = Array.isArray(body.messages) ? body.messages : [];

    const run = await start(orchestratorTurn, [messages, orchestratorModel()]);

    return createUIMessageStreamResponse({
        stream: run.readable.pipeThrough(createModelCallToUIChunkTransform()),
        // The id is what lets the client resume from where it left off instead
        // of rebuilding the turn — the reason this is a workflow at all.
        headers: {"x-workflow-run-id": run.runId}});
}
