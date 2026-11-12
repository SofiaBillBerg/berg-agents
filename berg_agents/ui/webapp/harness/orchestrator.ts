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
 * The orchestrator: an advisor that plans WITH the user and hands work to
 * specialists that are runs of their own.
 *
 * It is a `WorkflowAgent`, and that is the reason it lives in TypeScript: on a
 * pause this agent **suspends inside its run**, where berg's Python host ends
 * the pass and resumes as a new run. Suspension is what lets the user keep
 * talking to the orchestrator while a step waits — and planning with the user
 * mid-flight is the whole point of this agent.
 *
 * It owns no specialist logic. Each tool is one call into
 * `harness/specialists.ts`, so the orchestrator cannot drift from what the
 * Python side actually does.
 */

import {WorkflowAgent} from "@ai-sdk/workflow";
import {tool} from "ai";
import {z} from "zod";

import {
    answerSpecialist,
    listSpecialists,
    specialistReport,
    specialistState,
    startSpecialist,
    steerSpecialist,
    stopSpecialist} from "./specialists";

/**
 * The orchestrator's instructions.
 *
 * Written around the one thing that makes it different from a plain assistant:
 * the specialists are real runs with their own sessions, not tool calls. So the
 * agent is told to plan first, delegate one self-contained job at a time, report
 * honestly, and never pretend it did the work itself.
 */
const ORCHESTRATOR_INSTRUCTIONS = `You are the orchestrator and advisor for Berg Agents.

You plan work WITH the user. You do not do the work yourself: you have
full-scale specialists, and each one runs as its own task with its own record.

How to work:
1. Plan with the user. Ask what they actually want and how it fits together.
   Agree on the shape before delegating anything.
2. Delegate one self-contained job at a time with start_specialist, naming the
   specialist whose role matches. Say which one and why.
3. A specialist may stop and ask for your decision. Its state becomes "waiting":
   tell the user what it wants and what you recommend, then answer it with
   answer_specialist. Approving releases a gate the user put there, so the user
   is asked to confirm before it happens — put the request in your own words
   first, so they know what they are approving. Never imply you approved
   something on their behalf.
4. Report back what it actually did with specialist_report: its own words ("said")
   and the tool calls it made ("did"). Never claim work it did not do.
5. Use stop_specialist when the user wants it to stop, and steer_specialist to
   redirect it.

You are an advisor, not a black box: say what you are about to do, and when the
user changes direction, plan again.`;

/** The tools the orchestrator may call, each one a call into the Python side. */
export const orchestratorTools = {
    list_specialists: tool({
        description:
            "List the specialists available to delegate work to. Call this before " +
            "promising a specialist exists.",
        inputSchema: z.object({}),
        execute: async () => {
            const names = await listSpecialists();
            return {specialists: names};
        }}),

    start_specialist: tool({
        description:
            "Start a specialist's turn as a task of its own. Returns its run id, " +
            "which is the handle for reporting, steering and stopping it. Pass the " +
            "whole task: the specialist does not see this conversation.",
        inputSchema: z.object({
            agent: z
                .string()
                .describe("Which specialist, e.g. implementation, planner, curator."),
            task: z
                .string()
                .describe(
                    "The complete task in the user's words. Self-contained: the " +
                        "specialist cannot ask you follow-ups unless it uses its own " +
                        "question surface.",
                )}),
        // Starting a specialist begins a real run with real tools in the user's
        // project. It is reversible (stop_specialist), but the user should know
        // a run is starting before it does — that is the difference between an
        // advisor and a black box.
        needsApproval: true,
        execute: async ({agent, task}) => startSpecialist(agent, task)}),

    specialist_state: tool({
        description:
            "Read what a specialist is doing: pending, working, waiting on a " +
            "decision, or done.",
        inputSchema: z.object({runId: z.string()}),
        execute: async ({runId}) => specialistState(runId)}),

    specialist_report: tool({
        description:
            "Read what a specialist said and did, from its durable record. Use this " +
            "to report back truthfully rather than guessing.",
        inputSchema: z.object({runId: z.string()}),
        execute: async ({runId}) => specialistReport(runId)}),

    answer_specialist: tool({
        description:
            "Answer a specialist that is waiting on a decision. A steer travels with " +
            "the decision and supersedes what it was about to do.",
        inputSchema: z.object({
            runId: z.string(),
            approved: z.boolean(),
            reason: z.string().optional(),
            steer: z
                .string()
                .optional()
                .describe("New instruction that replaces the pending action.")}),
        // Letting a specialist proceed is the one action that carries the
        // user's authority rather than the orchestrator's: it releases a gate
        // the user put there. So approving asks the user first, and denying
        // does not — withdrawing work needs no permission.
        //
        // The workflow pauses here and the run suspends until an answer
        // arrives, which is exactly the capability this agent exists for.
        needsApproval: ({approved}) => approved === true,
        execute: async ({runId, approved, reason, steer}) =>
            answerSpecialist(runId, {approved, reason, steer})}),

    steer_specialist: tool({
        description:
            "Send the user's instruction to a specialist's turn. Check the returned " +
            "delivered flag: false means it waits for the specialist's next task.",
        inputSchema: z.object({
            runId: z.string(),
            text: z.string()}),
        execute: async ({runId, text}) => steerSpecialist(runId, text)}),

    stop_specialist: tool({
        description:
            "Stop a specialist. The backend picks the mechanism from its state: a " +
            "waiting task is withdrawn, a working one is terminated.",
        inputSchema: z.object({
            runId: z.string(),
            reason: z.string().optional()}),
        execute: async ({runId, reason}) => stopSpecialist(runId, reason)})};

/**
 * Build the orchestrator agent.
 *
 * @param model - A provider instance or gateway model id. berg's own model
 *   selection happens on the Python side; this is the orchestrator's own brain.
 * @returns A `WorkflowAgent` to run inside a workflow.
 */
export function buildOrchestrator(model: string | object): WorkflowAgent<any> {
    return new WorkflowAgent({
        model: model as never,
        instructions: ORCHESTRATOR_INSTRUCTIONS,
        tools: orchestratorTools});
}
