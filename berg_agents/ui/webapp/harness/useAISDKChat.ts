/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
* The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
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
 * Chat hook - wraps AI SDK v7's useChat to talk to the streaming backend.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. This hook provides a clean interface for
 * the App component.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages trigger
 * tool calls (file operations + run_task), which run the full BergAgents harness.
 */

import type {TextUIPart, UIMessage} from "ai";
import {DefaultChatTransport} from "ai";
import type {SetStateAction} from "react";
import {useEffect, useRef, useState} from "react";

import {useChat} from "@ai-sdk/react";

import {API_BASE} from "@/envConfig";

/** localStorage key for the live conversation (shared with History). */

/** localStorage key for the active server-side session id. */
export const SESSION_ID_KEY = "berg_session_id";

/** Max messages persisted (keeps quota usage bounded). */

/** Max chars kept per tool input/output in storage (display caps lower). */
const MAX_STORED_PART_CHARS = 2000;

/** Soft budget for the whole persisted payload (well under quota). */

/**
 * Slim a UIMessage list for localStorage: tool inputs/outputs are
 * truncated, so one big `read_file` can never blow the quota and
 * silently leave stale state behind (the restore "lottery").
 * Approval flow needs no old outputs, only part identities.
 *
 * @param msgs - Raw UI messages.
 * @returns JSON-safe slimmed copies.
 */
/**
 * Serialize messages to a quota-safe JSON string: slim first, then
 * drop oldest messages until under budget. Deterministic — the newest
 * turn always survives, so restores stop being a lottery.
 *
 * @param msgs - Raw UI messages (newest last).
 * @returns JSON string, or null when nothing serializable remains.
 */
export interface ChatMessage {
    id: string;
    role: "user" | "assistant" | "system";
    content: string;
    parts?: Array<Record<string, unknown>>;
    /** Model's private reasoning trace (omitted when empty). */
    reasoning?: string;
    /** Completed tool calls, rendered as collapsible cards. */
    toolCalls?: Array<{
        tool: string;
        input?: string;
        output?: string;
        state?: string;
    }>;
}

/** Max output chars kept per tool call for display/export. */
const MAX_TOOL_OUTPUT_CHARS = 4000;

/**
 * Extract completed tool calls from a UIMessage for card rendering.
 * Output text is capped so one giant result cannot flood the chat.
 */
function messageToolCalls(msg: UIMessage): ChatMessage["toolCalls"] {
    const calls: NonNullable<ChatMessage["toolCalls"]> = [];
    for (const part of msg.parts) {
        const p = part as unknown as Record<string, unknown>;
        const pType = typeof p.type === "string" ? p.type : "";
        if (pType !== "dynamic-tool" && !pType.startsWith("tool-")) continue;
        const name =
            (typeof p.toolName === "string" && p.toolName) ||
            (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
        let input = "";
        if (p.input != null) {
            try {
                input =
                    typeof p.input === "string"
                        ? p.input
                        : JSON.stringify(p.input, null, 2);
            } catch {
                input = "";
            }
        }
        let output: string | undefined;
        const raw = (p as { output?: unknown }).output;
        if (raw !== undefined && raw !== null) {
            try {
                output = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
            } catch {
                output = String(raw);
            }
            if (output.length > MAX_TOOL_OUTPUT_CHARS) {
                output = `${output.slice(0, MAX_TOOL_OUTPUT_CHARS)}\n… (output truncated)`;
            }
        }
        calls.push({
            tool: name,
            input: input || undefined,
            output,
            state: typeof p.state === "string" ? (p.state as string) : undefined});
    }
    return calls.length > 0 ? calls : undefined;
}

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

export interface UseAISDKChatReturn {
    messages: ChatMessage[];
    input: string;
    /** Direct state setter - compatible with InputBar's setInput prop. */
    setInput: (value: SetStateAction<string>) => void;
    /** Change handler - also compatible with InputBar. */
    handleInputChange: (
        e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => void;
    /** Send the current input message. */
    handleSend: () => void;
    isStreaming: boolean;
    error: string | null;
    isConnected: boolean;
    setMessages: (msgs: ChatMessage[]) => void;
    clearMessages: () => void;
    stop: () => void;
    sendMessage: (content: string) => Promise<void>;
    /** Stop the current response, then send (mid-stream steering). */
    interruptWith: (content: string) => Promise<void>;
    /** Replace the live conversation (history restore). */
    restoreMessages: (msgs: unknown[]) => void;
    /** Tool calls currently awaiting human approval. */
    pendingApprovals: PendingApproval[];
    /** Full active approval batch from the last assistant message: pending
     plus already-decided items (decided items stay visible with badges
     + undo until the resume fires and parts transition to output). */
    approvalBatch: PendingApproval[];
    /** Answer one approval (per-item stepwise decisions). */
    respondToApproval: (id: string, approved: boolean, reason?: string) => void;
    /** Answer every pending approval at once (batch convenience). */
    respondToAllApprovals: (approved: boolean, reason?: string) => Promise<void>;
    /** Replace a paused call's args (edit before approving). */
    editApprovalArgs: (id: string, args: unknown) => void;
    /** Withdraw a per-item decision before the batch resumes. */
    revertApproval: (id: string) => void;
    /** Visible system-recovery notice (failed-send auto-rejects). */
    systemNotice: string | null;
    /** Dismiss the system notice. */
    dismissSystemNotice: () => void;
    /** Active server-side session id (source of truth across browsers). */
    sessionId: string | null;
    /** Active session title for the chrome row. */
    sessionTitle: string | null;
    /** Start a new server-side session (clears the live chat). */
    newServerChat: () => Promise<void>;
    /** Open a server-side session by id (loads its transcript). */
    openSession: (id: string) => Promise<void>;
}

/**
 * Extract the model's private reasoning trace from a UIMessage.
 * Reasoning parts (`type: "reasoning"` from the adapter's ThinkingPart,
 * or "thinking"/"thinking-delta" variants from other providers) carry
 * the chain-of-thought the model streamed before acting - shown
 * collapsed in the UI. Some models (qwen-style) emit thinking inline
 * as `<think>...</think>` text instead of a typed part; those blocks
 * are lifted out of the text here too, so both flavors render.
 */
function extractReasoning(msg: UIMessage): string | undefined {
    const bits: string[] = [];
    for (const part of msg.parts) {
        const p = part as unknown as Record<string, unknown>;
        if (typeof p !== "object" || p === null) continue;
        const pType = typeof p.type === "string" ? p.type : "";
        if (
            pType === "reasoning" ||
            pType.startsWith("thinking") ||
            pType.startsWith("reasoning")
        ) {
            const text =
                (typeof p.text === "string" && p.text) ||
                (typeof p.reasoning === "string" && (p.reasoning as string)) ||
                "";
            if (text.trim() !== "") bits.push(text);
            continue;
        }
        // Inline <think> blocks inside regular text parts.
        if (pType === "text") {
            const text = typeof p.text === "string" ? (p.text as string) : "";
            const matches = text.match(/<think>([\s\S]*?)(?:<\/think>|$)/gi);
            if (matches) {
                for (const m of matches) {
                    const inner = m
                        .replace(/<\/?think>/i, "")
                        .replace(/<\/think>/i, "")
                        .trim();
                    if (inner) bits.push(inner);
                }
            }
        }
    }
    return bits.length > 0 ? bits.join("\n") : undefined;
}

/**
 * Extract displayable text from a UIMessage's parts (v7 API).
 * In v7, UIMessage has `parts` instead of `content`.
 *
 * Tool-call-only turns carry no text parts, which used to render as
 * empty bubbles. Tool invocations are summarized as `🔧 name(args...)`
 * lines so activity stays visible instead of blank. Inline <think>
 * blocks are moved into `reasoning` (see extractReasoning), not shown.
 */
function messageText(msg: UIMessage): string {
    const chunks: string[] = [];
    for (const part of msg.parts) {
        if (part.type === "text") {
            const raw = (part as unknown as TextUIPart).text;
            // Strip inline thinking blocks - they live in `reasoning` now.
            const cleaned = raw
                .replace(/<think>[\s\S]*?<\/think>/gi, "")
                .replace(/<\/?think>/gi, "")
                .trim();
            if (cleaned) chunks.push(cleaned);
            continue;
        }
        // Tool parts: `dynamic-tool` or `tool-<name>` shapes (v7).
        const p = part as unknown as Record<string, unknown>;
        const pType = typeof p.type === "string" ? p.type : "";
        if (pType === "dynamic-tool" || pType.startsWith("tool-")) {
            const name =
                (typeof p.toolName === "string" && p.toolName) ||
                (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
            let args = "";
            if (p.input != null && typeof p.input === "object") {
                try {
                    const entries = Object.entries(
                        p.input as Record<string, unknown>,
                    ).map(([k, v]) => {
                        const s = typeof v === "string" ? v : JSON.stringify(v);
                        return `${k}=${s}`;
                    });
                    args = entries.length > 0 ? `(${entries.join(", ")})` : "";
                } catch {
                    args = "";
                }
            }
            // Completed calls render as collapsible ToolCards downstream
            // (see messageToolCalls), so the text transcript keeps only a
            // marker for calls still in flight or awaiting approval.
            // (Exports re-attach outputs from `toolCalls` — see utils.)
            const output = (p as { output?: unknown }).output;
            const hasOutput = output !== undefined && output !== null;
            if (!hasOutput) {
                // A paused tool call renders as an approval prompt, not a plain call.
                // Parts without an approval id are ghosts from dead runs (see
                // sanitizeHistory): shown as expired, and the approval card
                // correctly ignores them since there is nothing to answer.
                const approval = (p as { approval?: unknown }).approval as
                    { id?: unknown } | undefined;
                const marker =
                    (p as { state?: unknown }).state === "approval-requested"
                        ? typeof approval?.id === "string"
                            ? "⏳ needs approval"
                            : "⏳ approval expired"
                        : "🔧";
                chunks.push(`${marker} ${name}${args}`);
            }
        }
    }
    return chunks.filter(Boolean).join("\n");
}

/**
 * Sanitize a restored conversation so stale single-use state can never
 * poison a fresh run. Approval responses are per-run nonces: replaying
 * an old `approval-responded` part makes the backend try to resume a
 * dead run (observed as cryptic failures). Parts answered but never
 * executed revert to `approval-requested` so the user is asked again;
 * malformed parts are dropped.
 *
 * Restores (`preserveLatest === false`) go further: the backend is
 * stateless, so EVERY restored approval id belongs to a dead run.
 * Their ids are stripped, which renders them as expired and makes
 * them unanswerable — a reload can never resurrect a blocking
 * approval card again.
 */
function sanitizeHistory(msgs: unknown[], preserveLatest: boolean): unknown[] {
    return msgs
        .filter(
            (m): m is Record<string, unknown> =>
                typeof m === "object" &&
                m !== null &&
                typeof (m as { id?: unknown }).id === "string" &&
                typeof (m as { role?: unknown }).role === "string" &&
                Array.isArray((m as { parts?: unknown }).parts),
        )
        .map((m, index, all) => {
            if (preserveLatest && index === all.length - 1) return m;
            return {
                ...m,
                parts: (m.parts as unknown[]).flatMap((p) => {
                    if (typeof p !== "object" || p === null) return [];
                    const part = p as {
                        type?: unknown;
                        state?: unknown;
                        approval?: unknown;
                    };
                    // Malformed parts can never resume — drop them.
                    if (typeof part.type !== "string") return [];
                    const isTool =
                        part.type === "dynamic-tool" || part.type.startsWith("tool-");
                    // Non-restore: the client never owns the system prompt
                    // (the backend builds it), so replayed system parts from a
                    // restored session are what triggers its strip warning.
                    if (!preserveLatest && (m as { role?: unknown }).role === "system") {
                        return [];
                    }
                    if (
                        isTool &&
                        part.state === "approval-responded" &&
                        (part as { output?: unknown }).output === undefined
                    ) {
                        // Answered but never executed: re-ask instead of replaying.
                        return [
                            {
                                ...part,
                                state: "approval-requested",
                                approval: undefined}];
                    }
                    if (
                        !preserveLatest &&
                        isTool &&
                        part.state === "approval-requested"
                    ) {
                        // Dead run (see docstring): expire instead of replaying.
                        const {approval: _dropped, ...rest} = part as Record<
                            string,
                            unknown
                        >;
                        return [rest];
                    }
                    return [{...part}];
                })};
        });
}

/**
 * Reason used for system-initiated rejections (failed sends, see the
 * error effect below). Deliberately retry-friendly: unlike an
 * explicit user rejection, a dead run says nothing about the action
 * itself, so the model should feel free to try again.
 */
const SYSTEM_RETRY_REASON =
    "System: the previous tool run failed before completing " +
    "(mismatched or interrupted approval state). This rejection is " +
    "automatic cleanup, NOT a human decision — you may retry the same " +
    "action with corrected arguments.";

/**
 * Main chat hook - wraps AI SDK v7's useChat to talk to /api/chat/stream.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages
 * trigger tool calls (file operations + run_task), which run the full
 * BergAgents harness. HITL approval requests surface as tool approval
 * parts in the AI SDK message stream.
 */
export function useAISDKChat(): UseAISDKChatReturn {
    // useChat v7 returns: messages, sendMessage, status, error, setMessages, stop
    // It does NOT return input/handleInputChange/handleSubmit - we manage input
    // state separately and call sendMessage directly.
    const [input, setInput] = useState("");

    // Server-side session: the authoritative conversation record shared
    // by every browser. Declared before useChat so the transport body
    // below always carries the current id.
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [sessionTitle, setSessionTitle] = useState<string | null>(null);

    const {
        messages: uiMessages,
        sendMessage: sdkSendMessage,
        status,
        error,
        setMessages: setUIMessages,
        stop,
        addToolApprovalResponse} = useChat({
        transport: new DefaultChatTransport({
            api: `${API_BASE}/api/chat/stream`,
            // Strip stale approval answers before every send. Anything
            // answered in an EARLIER message belongs to a dead run; only
            // the live last message may carry answers to the backend.
            // sessionId tells the backend which server-side session this
            // turn belongs to (any browser, any profile).
            prepareSendMessagesRequest: ({id, messages, trigger, messageId}) => ({
                body: {
                    id,
                    messages: sanitizeHistory(messages as unknown as unknown[], true),
                    trigger,
                    messageId,
                    sessionId}})}),
        // Resume a paused run after approvals. Per-item answers mark parts
        // one at a time; the resend fires once every pending part in the
        // paused message is answered (stepwise decisions never fire a
        // partial resume, which the backend rejects). Normal finished
        // turns never match.
        sendAutomaticallyWhen: ({messages}) => {
            const last = messages[messages.length - 1] as
                { role?: unknown; parts?: unknown } | undefined;
            if (!last || last.role !== "assistant" || !Array.isArray(last.parts)) {
                return false;
            }
            let answered = 0;
            let waiting = 0;
            for (const part of last.parts) {
                if (typeof part !== "object" || part === null) continue;
                const p = part as { type?: unknown; state?: unknown };
                const t = typeof p.type === "string" ? p.type : "";
                if (t !== "dynamic-tool" && !t.startsWith("tool-")) continue;
                if (p.state === "approval-responded") answered += 1;
                else if (p.state === "approval-requested") waiting += 1;
            }
            return answered > 0 && waiting === 0;
        }});

    const isStreaming = status === "streaming" || status === "submitted";

    // Tool calls paused for human approval (HITL). Derived from the raw
    // UI messages: any tool part in state "approval-requested".
    const pendingApprovals: PendingApproval[] = [];
    for (const msg of uiMessages) {
        for (const part of msg.parts) {
            const p = part as unknown as Record<string, unknown>;
            if (
                typeof p !== "object" ||
                p === null ||
                (p as { state?: unknown }).state !== "approval-requested"
            ) {
                continue;
            }
            const approval = (p as { approval?: unknown }).approval as
                { id?: unknown } | undefined;
            const approvalId = typeof approval?.id === "string" ? approval.id : null;
            if (!approvalId) continue;
            const pType = typeof p.type === "string" ? (p.type as string) : "";
            const toolName =
                (typeof p.toolName === "string" && (p.toolName as string)) ||
                (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
            let args = "";
            if (p.input != null && typeof p.input === "object") {
                try {
                    args = JSON.stringify(p.input);
                } catch {
                    args = "";
                }
            }
            if (!pendingApprovals.some((a) => a.id === approvalId)) {
                pendingApprovals.push({id: approvalId, toolName, args});
            }
        }
    }

    // Full active batch for the per-item approval card: derived from the
    // LAST assistant message only, including both pending
    // ("approval-requested") and already-decided ("approval-responded")
    // parts. Decided items stay visible with badges + undo until the
    // resume fires and parts transition to output state (at which point
    // the batch empties and the card disappears).
    const approvalBatch: PendingApproval[] = [];
    for (let i = uiMessages.length - 1; i >= 0; i--) {
        const msg = uiMessages[i];
        if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
        for (const part of msg.parts) {
            const p = part as unknown as Record<string, unknown>;
            if (
                typeof p !== "object" ||
                p === null ||
                (p.state !== "approval-requested" && p.state !== "approval-responded")
            ) {
                continue;
            }
            const approval = p.approval as
                { id?: unknown; approved?: unknown; reason?: unknown } | undefined;
            const approvalId = typeof approval?.id === "string" ? approval.id : null;
            if (!approvalId) continue;
            const pType = typeof p.type === "string" ? (p.type as string) : "";
            const toolName =
                (typeof p.toolName === "string" && (p.toolName as string)) ||
                (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
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
            if (!approvalBatch.some((a) => a.id === approvalId)) {
                approvalBatch.push({id: approvalId, toolName, args, decided, reason});
            }
        }
        // Only the last assistant message carries the live batch.
        break;
    }

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
        void addToolApprovalResponse({id, approved, reason});
    };

    // Answer EVERY pending approval at once (batch convenience).
    const respondToAllApprovals = async (approved: boolean, reason?: string) => {
        const ids = pendingApprovals.map((a) => a.id);
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
        setUIMessages(
            (prev) =>
                prev.map((msg) => {
                    const parts = msg.parts as unknown as Array<Record<string, unknown>>;
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
                        const approval = p.approval as { id?: unknown } | undefined;
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
        setUIMessages(
            (prev) =>
                prev.map((msg) => {
                    const parts = msg.parts as unknown as Array<Record<string, unknown>>;
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
                        const approval = p.approval as { id?: unknown } | undefined;
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

    // Convert AI SDK UIMessage[] to the simpler ChatMessage[] our UI expects.
    // Reasoning traces and tool calls ride along separately so the UI can
    // collapse them (reasoning block, ToolCards).
    const messages: ChatMessage[] = uiMessages.map((msg) => ({
        id: msg.id,
        role: msg.role as "user" | "assistant" | "system",
        content: messageText(msg),
        parts: [],
        reasoning: extractReasoning(msg),
        toolCalls: messageToolCalls(msg)}));

    const setMessages = (msgs: ChatMessage[]) => {
        setUIMessages(msgs as unknown as UIMessage[]);
    };

    const clearMessages = () => {
        setUIMessages([]);
    };

    // Restore server-session messages into the live chat.
    // Stored snapshots predate this load, so no paused run can be live.
    // Duplicate message ids (e.g. one request dumped to two UI messages)
    // are suffixed — React keys must be unique and ids are otherwise opaque.
    const restoreMessages = (msgs: unknown[]) => {
        if (!Array.isArray(msgs)) return;
        const clean = sanitizeHistory(msgs, false) as unknown as Array<{
            id?: unknown;
        }>;
        const seen = new Set<string>();
        for (const m of clean) {
            if (typeof m !== "object" || m === null || typeof m.id !== "string") {
                continue;
            }
            let id: string = m.id;
            if (seen.has(id)) {
                let n = 2;
                while (seen.has(`${id}-dup${n}`)) n += 1;
                id = `${id}-dup${n}`;
                m.id = id;
            }
            seen.add(id);
        }
        setUIMessages(clean as unknown as UIMessage[]);
    };

    // Open a server-side session: load its transcript, adopt its id.
    const openSession = async (id: string) => {
        const resp = await fetch(
            `${API_BASE}/api/sessions/${encodeURIComponent(id)}`,
        );
        if (!resp.ok) throw new Error(`Session ${id}: HTTP ${resp.status}`);
        const data = await resp.json();
        restoreMessages(Array.isArray(data.messages) ? data.messages : []);
        setSessionId(id);
        if (data.session && typeof data.session.title === "string") {
            setSessionTitle(data.session.title);
        }
        try {
            localStorage.setItem(SESSION_ID_KEY, id);
        } catch {
            // Private mode - session id stays in memory only.
        }
    };

    // Start a new server-side session (numbered title from the backend).
    const newServerChat = async () => {
        const resp = await fetch(`${API_BASE}/api/sessions`, {method: "POST"});
        if (!resp.ok) throw new Error(`New session: HTTP ${resp.status}`);
        const data = await resp.json();
        setUIMessages([]);
        setSessionId(typeof data.id === "string" ? data.id : null);
        setSessionTitle(typeof data.title === "string" ? data.title : null);
        try {
            if (typeof data.id === "string") {
                localStorage.setItem(SESSION_ID_KEY, data.id);
            }
        } catch {
            // Private mode - chat still works in memory.
        }
    };

    // Tracks whether the mount-restore below has run. The persist effect
    // must stay quiet until then: on a fresh mount uiMessages is empty,
    // and persisting that emptiness first would wipe the stored
    // conversation (this is what erased chats on tab switches).
    const restoredRef = useRef(false);

    // Visible notice for system-initiated recovery (failed sends, see
    // below). Rendered as an Alert by App — never smuggled into the
    // message list, so it can never poison a future send.
    const [systemNotice, setSystemNotice] = useState<string | null>(null);

    // Failed-send recovery: the backend is stateless, so any approval
    // parts pending when a send errors belong to a run that can never
    // resume — replaying them only reproduces the mismatch error
    // forever. Auto-reject them with the retry-friendly system reason
    // (NOT the firm user-rejection text) and tell the user visibly;
    // sendAutomaticallyWhen then resumes and the model may retry.
    // Already-handled ids are never touched twice, so a persistently
    // failing backend cannot loop sends forever.
    const handledErrorRef = useRef<unknown>(null);
    const autoRejectedIds = useRef<Set<string>>(new Set());
    useEffect(() => {
        if (!error || handledErrorRef.current === error) return;
        handledErrorRef.current = error;
        const ids: string[] = [];
        for (const msg of uiMessages) {
            if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
            for (const part of msg.parts) {
                const p = part as unknown as Record<string, unknown>;
                if (
                    typeof p !== "object" ||
                    p === null ||
                    (p.state !== "approval-requested" && p.state !== "approval-responded")
                ) {
                    continue;
                }
                const approval = p.approval as { id?: unknown } | undefined;
                if (
                    typeof approval?.id === "string" &&
                    !autoRejectedIds.current.has(approval.id)
                ) {
                    ids.push(approval.id);
                }
            }
        }
        if (ids.length === 0) return;
        for (const id of ids) autoRejectedIds.current.add(id);
        const stopped =
            /abort|cancel/i.test(String(error)) || status === "streaming";
        for (const id of ids) {
            void addToolApprovalResponse({
                id,
                approved: false,
                reason: stopped
                    ? "System: the run was stopped by the user before completing. " +
                    "This rejection is automatic cleanup — you may retry on request."
                    : SYSTEM_RETRY_REASON});
        }
        setSystemNotice(
            stopped
                ? "Run stopped — pending tool approvals were rejected as cleanup. Send a message to continue."
                : `A tool run failed (${String(error).slice(0, 200)}). Its pending approvals were auto-rejected so the conversation can continue — ask the model to retry.`,
        );
    }, [error, uiMessages, status]);

    // The backend refines a generated title once the first real user
    // message arrives (a greeting leaves it as "#N · date"), so the
    // header must re-read it after a settled turn. Without this the
    // title stays whatever it was at create time.
    useEffect(() => {
        if (!sessionId) return;
        if (isStreaming) return;
        let cancelled = false;
        const reverifyTitle = async () => {
            try {
                const resp = await fetch(
                    `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`,
                );
                if (!resp.ok || cancelled) return;
                const data = await resp.json();
                if (
                    !cancelled &&
                    data.session &&
                    typeof data.session.title === "string" &&
                    data.session.title !== sessionTitle
                ) {
                    setSessionTitle(data.session.title);
                }
            } catch {
                // Backend unreachable - the existing title stands.
            }
        };
        void reverifyTitle();
        return () => {
            cancelled = true;
        };
    }, [sessionId, sessionTitle, isStreaming]);

    // Restore the persisted conversation once, after mount. Server
    // first (shared across browsers), localStorage as offline fallback.
    // With no stored session id, mint one for this chat — the backend
    // creates the row lazily on the first send, so empty mounts never
    // spam numbered sessions.
    useEffect(() => {
        let cancelled = false;
        const restore = async () => {
            try {
                const storedId = localStorage.getItem(SESSION_ID_KEY);
                if (storedId) {
                    try {
                        const resp = await fetch(
                            `${API_BASE}/api/sessions/${encodeURIComponent(storedId)}`,
                        );
                        if (resp.ok && !cancelled) {
                            const data = await resp.json();
                            if (Array.isArray(data.messages) && data.messages.length > 0) {
                                setUIMessages(
                                    sanitizeHistory(
                                        data.messages,
                                        false,
                                    ) as unknown as UIMessage[],
                                );
                            }
                            setSessionId(storedId);
                            if (data.session && typeof data.session.title === "string") {
                                setSessionTitle(data.session.title);
                            }
                            return;
                        }
                    } catch {
                        // Server unreachable - fall through to local cache.
                    }
                } else {
                    // No session yet: adopt the project's active session when one
                    // exists (every window converges), else mint an id for this
                    // chat — the backend creates the row lazily on first send.
                    // Either way, fall through to adopt any local transcript.
                    try {
                        const currentResp = await fetch(`${API_BASE}/api/sessions/current`);
                        if (currentResp.ok && !cancelled) {
                            const current = await currentResp.json();
                            if (typeof current.id === "string" && current.id) {
                                await openSession(current.id);
                                return;
                            }
                        }
                    } catch {
                        // Server unreachable - mint locally below.
                    }
                    try {
                        const minted = crypto.randomUUID();
                        localStorage.setItem(SESSION_ID_KEY, minted);
                        if (!cancelled) setSessionId(minted);
                    } catch {
                        // Private mode - session stays server-minted per send.
                    }
                }
            } finally {
                if (!cancelled) restoredRef.current = true;
            }
            // No local copy: the server session is the only source.
        };
        void restore();
        return () => {
            cancelled = true;
        };
    }, []);

    // handleInputChange for a textarea/input - reads e.target.value.
    const handleInputChange = (
        e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
    ) => {
        setInput(e.target.value);
    };

    // handleSend sends the current input via AI SDK's sendMessage.
    // Clears the box immediately so the sent text doesn't linger.
    // A manual send resets recovery state: the user is driving again.
    const handleSend = () => {
        if (!input.trim() || isStreaming) return;
        const text = input;
        setInput("");
        setSystemNotice(null);
        autoRejectedIds.current.clear();
        void sdkSendMessage({text});
    };

    // Programmatic send (used by App's slash-command handler).
    // Also clears the input box when the sent content matches it.
    const sendMessage = async (content: string) => {
        if (!content.trim() || isStreaming) return;
        setInput((prev) => (prev.trim() === content.trim() ? "" : prev));
        setSystemNotice(null);
        autoRejectedIds.current.clear();
        await sdkSendMessage({text: content});
    };

    // Interrupt-and-redirect: stop the in-flight response, then send.
    // This is how the user steers mid-stream. stop() aborts the fetch;
    // the fresh send opens its own request, so no state gets tangled.
    const interruptWith = async (content: string) => {
        if (!content.trim()) return;
        stop();
        setInput("");
        setSystemNotice(null);
        autoRejectedIds.current.clear();
        await sdkSendMessage({text: content});
    };

    return {
        messages,
        input,
        setInput,
        handleInputChange,
        handleSend,
        isStreaming,
        error: error ? String(error) : null,
        isConnected: true,
        setMessages,
        clearMessages,
        stop,
        sendMessage,
        interruptWith,
        restoreMessages,
        pendingApprovals,
        approvalBatch,
        respondToApproval,
        respondToAllApprovals,
        editApprovalArgs,
        revertApproval,
        systemNotice,
        dismissSystemNotice: () => setSystemNotice(null),
        sessionId,
        sessionTitle,
        newServerChat,
        openSession};
}
