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
 * One orchestrator turn, as a durable workflow.
 *
 * This is the piece that needs a TypeScript runtime: on a pause the agent
 * SUSPENDS inside its run, so the user can keep talking to it while a step
 * waits. berg's Python host ends the pass instead, which is why the
 * orchestrator does not live there.
 *
 * The turn is deliberately thin — build the agent, hand it the conversation,
 * stream the parts — because the work itself happens in berg's Python
 * specialists, reached through the tools in `harness/orchestrator.ts`.
 */

import {buildOrchestrator} from "@/harness/orchestrator";
import type {ModelCallStreamPart} from "@ai-sdk/workflow";
import {convertToModelMessages, type LanguageModel, type UIMessage} from "ai";
import {getWritable} from "workflow";

/**
 * Run one orchestrator turn.
 *
 * The `"use workflow"` directive is what makes the run durable and resumable:
 * the Workflow runtime records each step, so a crash or a pause resumes rather
 * than restarting the turn.
 *
 * @param messages - The conversation as the UI holds it (`UIMessage[]`).
 * @param model - The orchestrator's brain: a serializable model bound to berg's
 *   own endpoint (see `harness/local-model.ts`). A gateway id would tie this to
 *   a hosted provider, and berg's models are local.
 * @returns The turn's messages, for the caller to persist.
 */
export async function orchestratorTurn(
    messages: UIMessage[],
    model: LanguageModel,
): Promise<{ messages: unknown[] }> {
    "use workflow";

    // The agent expects ModelMessage[], not UIMessage[]; the conversion is the
    // documented boundary between the UI's shape and the agent's.
    const modelMessages = await convertToModelMessages(messages);
    const agent = buildOrchestrator(model);

    const result = await agent.stream({
        messages: modelMessages,
        // Raw model parts on the workflow stream; the route converts them to UI
        // chunks with `createModelCallToUIChunkTransform`.
        writable: getWritable<ModelCallStreamPart>()});

    return {messages: result.messages};
}
