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

    const { messages, sendMessage, status, error, stop } = useChat({
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
            }})});

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

    return {
        messages,
        isStreaming: status === "streaming" || status === "submitted",
        error: error ? String(error.message ?? error) : null,
        send,
        stop,
        lastRunId};
}
