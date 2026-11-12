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
 * The orchestrator's conversation.
 *
 * Deliberately separate from `useAISDKChat`: that hook carries berg's
 * session machinery (a server session id, steering a live run, delegation
 * approvals) which belongs to the *Python* chat agent. The orchestrator is a
 * different agent with its own conversation and its own run — a
 * `WorkflowAgent` in this Next app — so it gets one thin hook over
 * `POST /api/orchestrator` rather than borrowing machinery that would send
 * its turns to the wrong place.
 *
 * One `useChat`, one transport. Anything the two eventually share should be
 * extracted from both, not bolted onto one.
 */

"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useCallback, useState } from "react";

/** What the page needs to render and drive the orchestrator. */
export interface UseOrchestratorChatReturn {
    /** The conversation, as the UI holds it. */
    messages: UIMessage[];
    /** Whether a turn is in flight. */
    isStreaming: boolean;
    /** The last error, if a turn failed outright. */
    error: string | null;
    /** Send the user's next message and start a turn. */
    send: (text: string) => Promise<void>;
    /** Stop the in-flight turn, if any. */
    stop: () => void;
    /** The workflow run id of the last turn, once the server reports it. */
    lastRunId: string | null;
    /** Approvals the orchestrator is waiting on, one per paused tool call. */
    pendingApprovals: PendingApprovalRequest[];
    /** Answer one: let the paused call run, or refuse it. */
    answerApproval: (approvalId: string, approved: boolean) => void;
}

/** One paused tool call, as the page needs it to ask the user. */
export interface PendingApprovalRequest {
    /** The id to answer. */
    approvalId: string;
    /** Which tool is waiting. */
    toolName: string;
    /** The arguments it intends to use, so the user can judge. */
    input: unknown;
}

/**
 * Drive the orchestrator's conversation.
 *
 * @returns The messages, the send/stop controls, and the last run id.
 */
export function useOrchestratorChat(): UseOrchestratorChatReturn {
    // The run id arrives on a response header, which the transport sees but
    // React does not — the callback fires outside render. State (not a ref) is
    // what makes the page re-render with the id once it lands.
    const [lastRunId, setLastRunId] = useState<string | null>(null);

    const {messages, sendMessage, status, error, stop, addToolApprovalResponse} =
        useChat({
        transport: new DefaultChatTransport({
            // Same origin: this is a Next route in this app, so it needs no
            // API_BASE. Under the `/api/*` proxy this path is explicitly NOT
            // forwarded to Python — filesystem routes win rewrites.
            api: "/api/orchestrator",
            /**
             * Adopt the workflow run id from the response.
             *
             * The server returns it as `x-workflow-run-id`; keeping it lets a
             * later slice reconnect to a suspended orchestration instead of
             * rebuilding the conversation from nothing.
             *
             * @param options - The transport's fetch options.
             * @returns The fetch response, after the id is recorded.
             */
            fetch: async (input, init) => {
                const response = await fetch(input, init);
                const runId = response.headers.get("x-workflow-run-id");
                // Setting state from a transport callback is safe: the callback
                // runs after the response starts, not during render.
                if (runId) setLastRunId(runId);
                return response;
            }}),
        // Resume the suspended run once the user has answered.
        //
        // Answering an approval only marks the part "approval-responded"; it
        // does not continue the turn by itself. Without this, the page showed
        // `approval-responded` and then simply stopped — the specialist never
        // started (found 2026-11-12 by clicking Allow and watching nothing
        // happen). Same rule as `useAISDKChat`, minus its ask_user branch,
        // which the orchestrator has no equivalent of: fire when at least one
        // part is answered and none is still waiting, so a multi-approval step
        // never resumes halfway.
        sendAutomaticallyWhen: ({ messages }) => {
            const last = messages[messages.length - 1] as
                { role?: unknown; parts?: unknown } | undefined;
            if (!last || last.role !== "assistant" || !Array.isArray(last.parts)) {
                return false;
            }
            let answered = 0;
            let waiting = 0;
            for (const part of last.parts) {
                if (typeof part !== "object" || part === null) continue;
                const p = part as Record<string, unknown>;
                const type = typeof p.type === "string" ? p.type : "";
                if (!type.startsWith("tool-")) continue;
                if (p.state === "approval-responded") answered += 1;
                else if (p.state === "approval-requested") waiting += 1;
            }
            return answered > 0 && waiting === 0;
        }});

    /**
     * Send one user message and start a turn.
     *
     * @param text - What the user typed.
     */
    const send = useCallback(
        async (text: string): Promise<void> => {
            const trimmed = text.trim();
            if (!trimmed) return;
            await sendMessage({ text: trimmed });
        },
        [sendMessage],
    );

    // A paused tool call arrives as a part with state "approval-requested".
    // Surfacing these is what turns the orchestrator's pause into something the
    // user can answer — without it the run stops and nothing can release it.
    const pendingApprovals: PendingApprovalRequest[] = [];
    for (const message of messages) {
        for (const part of message.parts as unknown as Array<
            Record<string, unknown>
        >) {
            if (String(part?.state ?? "") !== "approval-requested") continue;
            // `approval.id` is the field the SDK expects back in
            // addToolApprovalResponse; see the `approval-requested` variant in
            // ai's UIMessage part union.
            const approval = part.approval as {id?: unknown} | undefined;
            const approvalId = String(approval?.id ?? "");
            if (!approvalId) continue;
            pendingApprovals.push({
                approvalId,
                // "tool-start_specialist" -> "start_specialist"
                toolName: String(part.type ?? "").replace(/^tool-/, ""),
                input: part.input ?? part.args ?? null});
        }
    }

    /**
     * Answer a paused tool call.
     *
     * @param approvalId - Which request to answer.
     * @param approved - Whether the call may run.
     */
    const answerApproval = useCallback(
        (approvalId: string, approved: boolean): void => {
            // The SDK resolves the paused part and resumes the turn, which is
            // the whole point of the suspension model.
            addToolApprovalResponse({id: approvalId, approved});
        },
        [addToolApprovalResponse],
    );

    return {
        messages,
        isStreaming: status === "streaming" || status === "submitted",
        error: error ? String(error.message ?? error) : null,
        send,
        stop,
        lastRunId,
        pendingApprovals,
        answerApproval};
}
