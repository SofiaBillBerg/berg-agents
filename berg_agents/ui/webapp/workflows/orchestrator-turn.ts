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
 * One orchestrator SESSION, as a durable workflow.
 *
 * This is the piece that needs a TypeScript runtime: on a pause the agent
 * SUSPENDS inside its run, so the user can keep talking to it while a step
 * waits. berg's Python host ends the pass instead, which is why the
 * orchestrator does not live there.
 *
 * ONE RUN OWNS THE SESSION. This used to be one run per turn: every send started
 * a fresh `orchestratorTurn`, so an approval answer or a follow-up launched a
 * sibling run and the conversation re-planned from the client's view of it. The
 * world's own tables showed the cost — 74 orchestratorTurn runs, zero hooks, and
 * `berg.orchestrator_turns` holding one row per run instead of one per
 * conversation. The SDK's chat-session-modeling guide names that split exactly:
 * "Message injection: start another run" (single-turn) versus "resume a Hook"
 * (multi-turn). This file is the multi-turn shape.
 *
 * The loop:
 *
 *     turn n   agent.stream(...) → the run's own history grows
 *     await orchestratorSessionHook    ← the run SUSPENDS here, waiting
 *     turn n+1 the same run, the same history, the same run id
 *
 * The hook is created OUTSIDE the loop with the run id as its token, so the run
 * id is the session's address: a follow-up and an approval answer both resume it
 * by POSTing to /orchestrator/<runId>/message.
 *
 * The work itself happens in berg's Python specialists, reached through the tools
 * in `harness/orchestrator.ts` — this file only owns the conversation.
 */

import type { ModelMessage, UIMessage } from "ai";
import type { ModelCallStreamPart } from "@ai-sdk/workflow";
import type { BergModel } from "@/harness/berg-model";

import { convertToModelMessages } from "ai";
import { z } from "zod";
import { defineHook, getWorkflowMetadata, getWritable } from "workflow";

import { buildOrchestrator } from "@/harness/orchestrator";

/**
 * Everything the user can say while a session is parked.
 *
 * One hook, two payloads, because a message and an approval answer are the same
 * kind of thing — "the user spoke while the run was waiting" — and splitting
 * them across two hooks would give the caller two doors for one conversation.
 * A third kind ends the session explicitly, which is how a conversation is
 * closed without waiting out the turn ceiling.
 */
export const orchestratorSessionInput = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("message"),
    /** The user's words, verbatim. */
    text: z.string()}),
  z.object({
    kind: z.literal("approval"),
    /** The approval id the run's own stream advertised. */
    approvalId: z.string(),
    /** Whether the user allowed the call. */
    approved: z.boolean(),
    /** Why not, when denied — or what is being released, when allowed. */
    reason: z.string().optional()}),
  z.object({
    kind: z.literal("done")})]);

/** What the hook carries, as the workflow's own type contract. */
export type OrchestratorSessionInput = z.infer<typeof orchestratorSessionInput>;

/**
 * The session's hook.
 *
 * Declared once at module level and created once per run, addressed by that
 * run's id. The schema is not decoration: the installed `workflow` 5.7.1
 * validates the payload against it on every `resume`, so a malformed answer is
 * refused at the boundary rather than handed to a parked run as data it cannot
 * use. This is the root `defineHook` — the variant a route imports, which is
 * the one that takes a schema and whose `resume` works outside a workflow; the
 * in-workflow variant takes no schema and its `resume` throws by design.
 *
 * Verified on a probe before this was written (see
 * `.opencode/plans/orchestrator-session-plan.md`): a hook registers, an approval
 * answer resumes the SAME run, and the gated tool executes inside it.
 */
export const orchestratorSessionHook = defineHook({
  schema: orchestratorSessionInput});

/**
 * How many turns one session may run before it returns.
 *
 * A bound rather than "forever" because a session holds a hook open for its
 * whole life, and the SDK's own guidance is to split a conversation into bounded
 * runs once it grows long. 100 is far above a planning conversation and is the
 * ceiling `generate()` applies too.
 */
const MAX_TURNS = 100;

/**
 * Run one orchestrator session: the run owns the model history, the hook carries
 * every follow-up.
 *
 * @param messages - The conversation as the UI holds it (`UIMessage[]`), for the
 *   turns that came before the first suspend.
 * @param model - The brain this session runs on, already resolved to its
 *   endpoint and wire by the route through berg's own provider configuration.
 *   It crosses the step boundary as data and is rebuilt on the far side, which
 *   is why it is built here and not derived here.
 * @returns The run's final model messages, for a caller that persists them.
 */
export async function orchestratorTurn(
  messages: UIMessage[],
  model: BergModel,
): Promise<{ messages: unknown[] }> {
  "use workflow";

  // The run id is the session id: the hook is addressed by it and the start
  // route's `x-workflow-run-id` header is what the client keeps.
  const { workflowRunId } = getWorkflowMetadata();
  const hook = orchestratorSessionHook.create({ token: workflowRunId });
  const writable = getWritable<ModelCallStreamPart>();

  // The agent speaks ModelMessage[], not UIMessage[]; this conversion is the
  // documented boundary between the UI's shape and the agent's. It runs here
  // because it is a step's work, not a workflow body's.
  const modelMessages = await convertToModelMessages(messages);
  const agent = buildOrchestrator(model);

  // The run's own history, which is what every following turn is built on. This
  // is the half the old per-turn runs lost: each of them was seeded from the
  // CLIENT's view, and the finished run's real history — the one carrying the
  // specialist's actual tool results — was never fed back, which is why the
  // orchestrator kept re-delegating work a specialist had already done.
  let history: ModelMessage[] = modelMessages;

  for (let turn = 0; turn < MAX_TURNS; turn++) {
    // The last turn closes: every earlier one holds the stream open so the
    // session continues in it, and the final one emits its finish chunk and lets
    // the stream close. A stream that ends with no finish leaves the client
    // without a completed message and sends it reconnecting forever looking for
    // one (measured on the probe).
    const isLast = turn === MAX_TURNS - 1;
    const result = await agent.stream({
      messages: history,
      writable,
      preventClose: !isLast,
      sendFinish: !isLast});

    // Carried forward minus the system message: the agent puts its own
    // instructions back on every call, and berg's local endpoint rejects a
    // history that carries one too ("System messages are not allowed in the
    // prompt or messages fields"). Filtering here rather than trusting the
    // provider keeps the carry-forward exact everywhere else.
    history = (result.messages as ModelMessage[]).filter(
      (message) => message.role !== "system",
    );

    // The session's last turn takes no further input: awaiting the hook here
    // would park the run a second time before returning, leaving it suspended
    // with a live hook rather than completed.
    if (isLast) break;

    const input = await hook;

    if (input.kind === "done") break;

    if (input.kind === "approval") {
      // The approval answer, in the ModelMessage shape the agent consumes: a
      // `tool` message carrying the approval-response part (an assistant message
      // holding it is rejected). The tool call and its request are ALREADY in
      // this run's history from the pass that parked, so only the response is
      // appended — and appending it to the run's OWN history is what continues
      // the run's durable tool flow, in this run rather than a sibling.
      history = [
        ...history,
        {
          role: "tool",
          content: [
            {
              type: "tool-approval-response",
              approvalId: input.approvalId,
              approved: input.approved,
              ...(input.reason ? { reason: input.reason } : {})}]} as unknown as ModelMessage];
    } else {
      // A user turn, appended to the run's own history so the model sees it on
      // this pass exactly as the SDK's `enqueue` rule for a deferred pause says
      // it should be.
      history = [
        ...history,
        {
          role: "user",
          content: input.text} as ModelMessage];
    }
  }

  return { messages: history };
}
