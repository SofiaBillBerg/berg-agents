/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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
 * HITL - the two paused-call surfaces and the answers that release them.
 *
 * A run pauses on exactly two kinds of tool call: one that wants an
 * approval decision, and one that wants an answer (ask_user_question).
 * Both render as cards, both are answered one item at a time, and both
 * release the run only once EVERY pending call in the paused message is
 * answered - a partial answer set is what the backend rejects.
 *
 * The pair belongs in one module because their rules are the same rules
 * read twice: exclude the other kind, read the last assistant message,
 * treat a reload's dump as "everything still requested", and never hand
 * the SDK an id it cannot resolve (addToolApprovalResponse and
 * addToolOutput both throw on an unknown id and wedge the run).
 *
 * Three parts here:
 * - the derivations (what is pending right now) - pure, so the shapes
 *   can be checked without a browser;
 * - the resolvability predicates (may this id still be answered);
 * - the responders, built per render so they read the messages the user
 *   is looking at, exactly as the hook's own closures used to.
 */

import type {UIMessage} from "ai";
import type {PendingQuestion, PendingQuestionAnswer} from "./askUser";

import {
    ASK_USER_TOOL_NAME,
    isQuestionAnswerPayload,
    parseQuestionCall} from "./askUser";
import {partToolName} from "./messageParts";

/** One approval card: a tool call the user decides on. */
export interface PendingApproval {
    /** Approval id - pass back to respondToApproval */
    id: string;
    /** Tool the model wants to run (e.g. "write_file") */
    toolName: string;
    /** Human-readable argument summary */
    args: string;
    /** True once the user decided this item (decided items stay in the
        batch list so they can be retracted before the resume fires). */
    decided?: boolean;
    /** User's denial reason, when rejected with one. */
    reason?: string;
}

/**
 * Tool calls paused for human approval, across the whole conversation.
 *
 * Any tool part in state "approval-requested" with a readable approval
 * id is pending. Questions have their own card and are answered by tool
 * call id, not approval id; a reloaded run renders them as
 * approval-requested, so they must not leak into this batch.
 *
 * @param messages - The raw UI messages.
 * @returns Pending approvals, de-duplicated by id.
 */
export function pendingApprovalsFrom(
    messages: readonly UIMessage[],
): PendingApproval[] {
    const pendingApprovals: PendingApproval[] = [];
    for (const msg of messages) {
        for (const part of msg.parts) {
            const p = part as unknown as Record<string, unknown>;
            if (
                typeof p !== "object" ||
                p === null ||
                (p as {state?: unknown}).state !== "approval-requested"
            ) {
                continue;
            }
            const approval = (p as {approval?: unknown}).approval as
                | {id?: unknown}
                | undefined;
            const approvalId =
                typeof approval?.id === "string" ? approval.id : null;
            if (!approvalId) continue;
            const toolName = partToolName(p);
            if (toolName === ASK_USER_TOOL_NAME) continue;
            let args = "";
            if (p.input != null && typeof p.input === "object") {
                try {
                    args = JSON.stringify(p.input);
                } catch {
                    args = "";
                }
            }
            if (!pendingApprovals.some((a) => a?.id === approvalId)) {
                pendingApprovals.push({id: approvalId, toolName, args});
            }
        }
    }
    return pendingApprovals;
}

/**
 * Full active batch for the per-item approval card.
 *
 * Derived from the LAST assistant message only, including both pending
 * ("approval-requested") and already-decided ("approval-responded")
 * parts. Decided items stay visible with badges + undo until the resume
 * fires and parts transition to output state (at which point the batch
 * empties and the card disappears).
 *
 * @param messages - The raw UI messages.
 * @returns The batch, de-duplicated by id.
 */
export function approvalBatchFrom(
    messages: readonly UIMessage[],
): PendingApproval[] {
    const approvalBatch: PendingApproval[] = [];
    for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
        for (const part of msg.parts) {
            // A part can be a hole (undefined) after the SDK rewrites
            // the array mid-stream; every field read below is guarded so a
            // sparse entry can never throw inside the render pass.
            const p = part as unknown as Record<string, unknown>;
            if (typeof p !== "object" || p === null) continue;
            if (
                p.state !== "approval-requested" &&
                p.state !== "approval-responded"
            ) {
                continue;
            }
            const approval = p.approval as
                | {id?: unknown; approved?: unknown; reason?: unknown}
                | undefined;
            const approvalId =
                typeof approval?.id === "string" ? approval.id : null;
            if (!approvalId) continue;
            const toolName = partToolName(p);
            // Same exclusion as pendingApprovalsFrom: a question answered
            // before a reload comes back as approval-requested and would
            // otherwise masquerade as an approval in this batch.
            if (toolName === ASK_USER_TOOL_NAME) continue;
            let args = "";
            if (p.input != null && typeof p.input === "object") {
                try {
                    args = JSON.stringify(p.input);
                } catch {
                    args = "";
                }
            }
            const decided = p.state === "approval-responded";
            const reason =
                typeof approval?.reason === "string" ? approval.reason : undefined;
            if (!approvalBatch.some((a) => a?.id === approvalId)) {
                approvalBatch.push({id: approvalId, toolName, args, decided, reason});
            }
        }
        // Only the last assistant message carries the live batch.
        break;
    }
    return approvalBatch;
}

/**
 * Full active question batch, mirroring the approval batch.
 *
 * The LAST assistant message's ask_user_question calls, both pending
 * ("input-available" on the live wire, "approval-requested" after a
 * reload - the dump marks every deferred call that way) and answered
 * (their output holds the canonical payload until the resume fires and
 * the server overwrites it with the rendered result).
 *
 * @param messages - The raw UI messages.
 * @returns The batch, de-duplicated by tool call id.
 */
export function questionBatchFrom(
    messages: readonly UIMessage[],
): PendingQuestion[] {
    const questionBatch: PendingQuestion[] = [];
    for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
        for (const part of msg.parts) {
            const p = part as unknown as Record<string, unknown>;
            if (typeof p !== "object" || p === null) continue;
            if (partToolName(p) !== ASK_USER_TOOL_NAME) continue;
            const id = typeof p.toolCallId === "string" ? p.toolCallId : null;
            if (!id) continue;
            const answered =
                p.state === "output-available" && isQuestionAnswerPayload(p.output);
            if (
                !answered &&
                p.state !== "input-available" &&
                p.state !== "approval-requested"
            ) {
                // Completed turns hold rendered results (no payload shape)
                // and dead-run ghosts were expired by sanitizeHistory;
                // neither is answerable, so neither belongs in the batch.
                continue;
            }
            const declined =
                answered && (p.output as {cancelled?: unknown}).cancelled === true;
            if (!questionBatch.some((q) => q.id === id)) {
                questionBatch.push({
                    id,
                    questions: parseQuestionCall(p.input),
                    answered,
                    declined});
            }
        }
        // Only the last assistant message carries the live batch.
        break;
    }
    return questionBatch;
}

/**
 * Whether the SDK can still resolve an approval id.
 *
 * addToolApprovalResponse matches on a part in state
 * "approval-requested" whose `approval.id` equals the id, and it does not
 * guard `approval` - an id with no such part throws inside the SDK and
 * wedges the run. Every approve path goes through this so the client
 * never asks the SDK to resolve a ghost.
 *
 * @param messages - The raw UI messages.
 * @param id - Approval id a click wants to answer.
 * @returns True when a part in this message state still carries it.
 */
export function approvalResolvableIn(
    messages: readonly UIMessage[],
    id: string,
): boolean {
    return messages.some((msg) =>
        msg.parts?.some(
            (part) =>
                typeof part === "object" &&
                part !== null &&
                (part as {state?: unknown}).state === "approval-requested" &&
                (part as {approval?: {id?: unknown}}).approval?.id === id,
        ),
    );
}

/**
 * Whether the SDK can still resolve a question's tool call id.
 *
 * addToolOutput throws on an unknown id and wedges the run, so the same
 * guard as approvals applies: the part must still be there and must not
 * already carry a canonical answer payload.
 *
 * @param messages - The raw UI messages.
 * @param id - Tool call id a click wants to answer.
 * @returns True when a part in this message state is still answerable.
 */
export function questionResolvableIn(
    messages: readonly UIMessage[],
    id: string,
): boolean {
    return messages.some((msg) =>
        (msg.parts ?? []).some(
            (part) =>
                typeof part === "object" &&
                part !== null &&
                partToolName(part as unknown as Record<string, unknown>) ===
                    ASK_USER_TOOL_NAME &&
                (part as unknown as {toolCallId?: unknown}).toolCallId === id &&
                !(
                    (part as unknown as {state?: unknown}).state ===
                        "output-available" &&
                    isQuestionAnswerPayload(
                        (part as unknown as {output?: unknown}).output,
                    )
                ),
        ),
    );
}

/** What the responders need from the chat hook's current render. */
export interface HitlResponderDeps {
    /** The messages as the user currently sees them. */
    messages: readonly UIMessage[];
    /** Mark one approval decided (AI SDK). */
    addToolApprovalResponse: (response: {
        id: string;
        approved: boolean;
        reason?: string;
    }) => Promise<unknown> | unknown;
    /** Write a tool's output (AI SDK) - the answer channel. */
    addToolOutput: (output: {
        tool: string;
        toolCallId: string;
        output: unknown;
    }) => Promise<unknown> | unknown;
    /** Replace the messages in place (AI SDK) - the edit/revert channel. */
    setMessages: (updater: (prev: UIMessage[]) => UIMessage[]) => void;
}

/** The six answer actions the UI drives. */
export interface HitlResponders {
    respondToApproval: (id: string, approved: boolean, reason?: string) => void;
    respondToAllApprovals: (
        approved: boolean,
        reason?: string,
    ) => Promise<void>;
    editApprovalArgs: (id: string, args: unknown) => void;
    revertApproval: (id: string) => void;
    respondToQuestion: (
        id: string,
        answers: PendingQuestionAnswer[],
        declined: boolean,
    ) => void;
    declineAllQuestions: () => void;
}

/**
 * Build the six HITL responders against one render's messages.
 *
 * Called on every render so the closures read exactly the messages the
 * user is looking at - the same capture the hook's own inline functions
 * had when they read `uiMessages` directly.
 *
 * @param deps - The hook's current messages and its three SDK channels.
 * @returns The six responders.
 */
export function createHitlResponders(
    deps: HitlResponderDeps,
): HitlResponders {
    const {messages, addToolApprovalResponse, addToolOutput, setMessages} = deps;

    // Answer ONE approval (per-item stepwise decision). The SDK marks
    // that single part as responded; the resume only fires once EVERY
    // pending part in the paused message is answered (see
    // sendAutomaticallyWhen), so partial decisions never trigger a
    // partial resume — the backend requires a complete answer set.
    const respondToApproval = (
        id: string,
        approved: boolean,
        reason?: string,
    ) => {
        if (!approvalResolvableIn(messages, id)) {
            console.warn(
                `[useAISDKChat] Approval ${id} is not answerable in this message ` +
                    `state (stale or restored run) - ignoring the click.`,
            );
            return;
        }
        void addToolApprovalResponse({id, approved, reason});
    };

    // Answer EVERY pending approval at once (batch convenience).
    const respondToAllApprovals = async (
        approved: boolean,
        reason?: string,
    ) => {
        const ids = pendingApprovalsFrom(messages)
            .map((a) => a?.id)
            .filter((id): id is string => Boolean(id) && approvalResolvableIn(messages, id));
        for (const id of ids) {
            await addToolApprovalResponse({id, approved, reason});
        }
    };

    // Replace a paused call's args before approving (edit). Updates the
    // part's input in place; the backend adapter maps an approved call's
    // part input to ToolApproved(override_args=...), so the edited args
    // reach the actual tool execution. Allowed in both states: the
    // resume only fires once EVERY pending part is answered, so editing
    // still lands in time until the last decision is made.
    const editApprovalArgs = (id: string, args: unknown) => {
        setMessages((prev) =>
            prev.map((msg) => {
                const parts = msg.parts as unknown as Array<
                    Record<string, unknown>
                >;
                if (!Array.isArray(parts)) return msg;
                let changed = false;
                const nextParts = parts.map((p) => {
                    if (
                        typeof p !== "object" ||
                        p === null ||
                        (p.state !== "approval-requested" &&
                            p.state !== "approval-responded")
                    ) {
                        return p;
                    }
                    const approval = p.approval as {id?: unknown} | undefined;
                    if (approval?.id !== id) return p;
                    changed = true;
                    return {...p, input: args};
                });
                return changed ? {...msg, parts: nextParts} : msg;
            }) as unknown as UIMessage[],
        );
    };

    // Withdraw a per-item decision before the batch resumes: flip the
    // part back to approval-requested so the user can reconsider. The
    // part reappears in the approval card and no longer counts as
    // answered, so the resume is held back again.
    const revertApproval = (id: string) => {
        setMessages((prev) =>
            prev.map((msg) => {
                const parts = msg.parts as unknown as Array<
                    Record<string, unknown>
                >;
                if (!Array.isArray(parts)) return msg;
                let changed = false;
                const nextParts = parts.map((p) => {
                    if (
                        typeof p !== "object" ||
                        p === null ||
                        p.state !== "approval-responded"
                    ) {
                        return p;
                    }
                    const approval = p.approval as {id?: unknown} | undefined;
                    if (approval?.id !== id) return p;
                    changed = true;
                    return {
                        ...p,
                        state: "approval-requested",
                        // Drop the answer so the wire payload carries a clean
                        // requested-state approval again.
                        approval: {...approval, approved: undefined, reason: undefined}};
                });
                return changed ? {...msg, parts: nextParts} : msg;
            }) as unknown as UIMessage[],
        );
    };

    // Answer ONE ask_user_question call. The payload written into the
    // part's output is the canonical wire shape the server's adapter
    // validates against the question that was asked (the harness's
    // check_response): every question answered with labels it offered
    // or a nonblank custom answer, or a bare decline. addToolOutput
    // rewrites the part to output-available and re-evaluates
    // sendAutomaticallyWhen, which resumes the run once every pending
    // part in the paused message is answered.
    const respondToQuestion = (
        id: string,
        answers: PendingQuestionAnswer[],
        declined: boolean,
    ) => {
        if (!questionResolvableIn(messages, id)) {
            console.warn(
                `[useAISDKChat] Question ${id} is not answerable in this ` +
                    `message state (stale or restored run) - ignoring the click.`,
            );
            return;
        }
        // Canonical payload: wire keys are the harness's (snake_case), and
        // a decline carries no answers - exactly what check_response
        // demands. Whether the SDK can still resolve a toolCallId is
        // guarded above for the same reason as approvals: addToolOutput
        // throws on an unknown id and wedges the run.
        const payload = {
            answers: declined
                ? []
                : answers.map((a) => ({
                      header: a.header,
                      selected: a.selected,
                      custom_answer: a.customAnswer ?? null})),
            cancelled: declined};
        void addToolOutput({
            tool: "dynamic-tool",
            toolCallId: id,
            output: payload});
    };

    // Decline every pending question in the batch (batch convenience).
    const declineAllQuestions = () => {
        for (const q of questionBatchFrom(messages)) {
            if (!q.answered) respondToQuestion(q.id, [], true);
        }
    };

    return {
        respondToApproval,
        respondToAllApprovals,
        editApprovalArgs,
        revertApproval,
        respondToQuestion,
        declineAllQuestions};
}
