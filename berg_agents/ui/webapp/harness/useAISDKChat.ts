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
import type {SetStateAction} from "react";

import {DefaultChatTransport} from "ai";
import {useCallback, useEffect, useRef, useState} from "react";
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

/**
 * The wire tool name of the harness's ask-user call. A question pauses
 * the run exactly like an approval does; every card, marker and trigger
 * below branches on this name to keep the two surfaces separate.
 */
const ASK_USER_TOOL_NAME = "ask_user_question";

// Client-side hint for transport failures - the one failure class whose
// cause the client can see better than the server (it never reached the
// backend). Provider-level diagnosis stays server-side and arrives on the
// run's status; the client never duplicates that matching logic.
function clientFailureHint(detail: string): string | undefined {
    if (/fetch|network|econn|connection|refused|timeout/i.test(detail)) {
        return "The chat backend could not be reached — is the server running?";
    }
    return undefined;
}

export interface PendingQuestionOption {
    /** One offered choice, kept verbatim - the answer is keyed by label. */
    label: string;
    /** What choosing this option means, when the model provided it. */
    description?: string;
}

export interface PendingQuestionData {
    /** Short label naming the question; the answer is keyed by it. */
    header: string;
    /** The full question text. */
    question: string;
    /** Whether the user may pick more than one option. */
    multiSelect: boolean;
    options: PendingQuestionOption[];
}

/** One answer inside a submitted response (wire keys are snake_case). */
export interface PendingQuestionAnswer {
    header: string;
    selected: string[];
    customAnswer?: string;
}

export interface PendingQuestion {
    /** Tool call id - pass back to respondToQuestion. */
    id: string;
    /** The call's questions, parsed from its args; empty when unreadable. */
    questions: PendingQuestionData[];
    /** True once an answer payload is written (badge until the resume
     fires and the server overwrites the output with the result). */
    answered: boolean;
    /** True when the written payload declines the questions. */
    declined: boolean;
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

/**
 * One failure the failure dialog presents. The dialog is the ONE
 * surface for fatal failures (a warning toast + a hidden debug line
 * used to duplicate it); the journal text in the transcript is the
 * separate durable record and stays.
 */
export interface FailureNotice {
    /** Which class of failure this is - the dialog titles on it. */
    kind: "send" | "run" | "recovery";
    /** The raw error text, truncated for display. */
    detail: string;
    /**
     * Actionable hint, when one is known. Server-side failures carry the
     * backend's hint (one hint logic, no client duplication); client-side
     * failures derive a network hint from the error text.
     */
    hint?: string;
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
    steer: (content: string) => Promise<void>;
    /** Messages the agent has not read yet (the steering strip above the
     * input). An entry here is queued on the server's run; once the model
     * receives it, it moves into the transcript and leaves this list. */
    pendingSteering: string[];
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
    /** Full active question batch from the last assistant message:
     pending calls plus already-answered ones (answered calls show a
     badge until the resume fires and the server overwrites their
     outputs with the rendered results). */
    questionBatch: PendingQuestion[];
    /** Answer one ask_user_question call: its answers, or a decline. */
    respondToQuestion: (
        id: string,
        answers: PendingQuestionAnswer[],
        declined: boolean,
    ) => void;
    /** Decline every pending question in the batch at once. */
    declineAllQuestions: () => void;
    /** The active failure notice, or null: the one input to the
     * failure dialog. Replaces the old systemNotice alert - its
     * recovery content is now the "recovery" kind here. */
    failureNotice: FailureNotice | null;
    /** Dismiss the failure dialog (read and acknowledged). */
    dismissFailureNotice: () => void;
    /** Retry the last failed user send (send-kind failures only). */
    retryLast: () => void;
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
 * Read a tool part's wire name. Typed parts carry it in the `type` prefix
 * (`tool-<name>`); a part the client normalized to a dynamic tool carries a
 * separate `toolName` field instead. One derivation for every call site.
 */
function partToolName(p: Record<string, unknown>): string {
    const type = typeof p.type === "string" ? p.type : "";
    return (
        (typeof p.toolName === "string" && p.toolName) ||
        (type.startsWith("tool-") ? type.slice("tool-".length) : "tool")
    );
}

/**
 * Whether a part's output is a canonical question-answer payload - the
 * `{answers: [{header, ...}], cancelled}` shape respondToQuestion writes
 * and the server's adapter expects. Once the resume lands, the server
 * overwrites the output with the RENDERED result (`{header: [labels]}` or
 * the DECLINED sentence), which never matches this shape - so spent
 * answers cannot re-arm a resume and completed turns stay completed.
 */
function isQuestionAnswerPayload(output: unknown): boolean {
    if (typeof output !== "object" || output === null) return false;
    const o = output as Record<string, unknown>;
    if (typeof o.cancelled !== "boolean") return false;
    if (!Array.isArray(o.answers)) return false;
    return o.answers.every(
        (entry) =>
            typeof entry === "object" &&
            entry !== null &&
            typeof (entry as Record<string, unknown>).header === "string",
    );
}

/**
 * Parse one ask_user_question call's questions from its input args
 * (`{questions: [{header, question, multi_select, options}]}`). The
 * harness validates the same shape before the model's call is accepted,
 * so anything malformed here is a dead-run ghost: it renders as a raw
 * call, never as an answerable card.
 */
function parseQuestionCall(input: unknown): PendingQuestionData[] {
    if (typeof input !== "object" || input === null) return [];
    if (!Array.isArray((input as Record<string, unknown>).questions)) {
        return [];
    }
    const out: PendingQuestionData[] = [];
    for (const raw of (input as Record<string, unknown>)
        .questions as unknown[]) {
        if (typeof raw !== "object" || raw === null) return [];
        const q = raw as Record<string, unknown>;
        if (typeof q.header !== "string" || typeof q.question !== "string") {
            return [];
        }
        if (!Array.isArray(q.options)) return [];
        const options: PendingQuestionOption[] = [];
        for (const opt of q.options) {
            if (typeof opt !== "object" || opt === null) return [];
            const o = opt as Record<string, unknown>;
            if (typeof o.label !== "string") return [];
            options.push({
                label: o.label,
                description:
                    typeof o.description === "string" ? o.description : undefined});
        }
        out.push({
            header: q.header,
            question: q.question,
            multiSelect: q.multi_select === true,
            options});
    }
    return out;
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
            const name = partToolName(p);
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
                // A paused tool call renders by kind: questions get their
                // own marker so a pause reads as "the model is asking",
                // never like a system gate. Parts without an approval id
                // are ghosts from dead runs (see sanitizeHistory): shown
                // as expired, and the cards correctly ignore them since
                // there is nothing to answer.
                const approval = (p as { approval?: unknown }).approval as
                    { id?: unknown } | undefined;
                const marker =
                    name === ASK_USER_TOOL_NAME
                        ? "❓ question pending"
                        : (p as { state?: unknown }).state ===
                              "approval-requested"
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
 * malformed parts are dropped. A question answer payload sitting in an
 * earlier message is the same nonce problem in a different shape, so it
 * is expired to an honest sentence (only the live last message may
 * carry answers to the backend).
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
                        // `approval` must stay a real object AND carry an `id`:
                        // the AI SDK's addToolApprovalResponse reads
                        // `part.approval.id` with no optional chaining, so both
                        // an undefined approval and a missing id leave an
                        // unanswerable card that throws on the next click.
                        // Without an id there is nothing to ask again, so the
                        // part expires like any other dead-run approval.
                        const previous =
                            typeof part.approval === "object" &&
                            part.approval !== null
                                ? (part.approval as { id?: unknown })
                                : undefined;
                        const approvalId =
                            typeof previous?.id === "string"
                                ? previous.id
                                : undefined;
                        if (!approvalId) {
                            const {approval: _dropped, ...rest} = part as Record<
                                string,
                                unknown
                            >;
                            return [{...rest, state: "output-denied"}];
                        }
                        return [
                            {
                                ...part,
                                state: "approval-requested",
                                approval: {
                                    ...previous,
                                    id: approvalId,
                                    approved: undefined,
                                    reason: undefined}}];
                    }
                    if (
                        !preserveLatest &&
                        isTool &&
                        part.state === "approval-requested"
                    ) {
                        // Dead run (see docstring): expire instead of replaying.
                        //
                        // The state MUST leave "approval-requested" here. The
                        // AI SDK's addToolApprovalResponse filters with
                        // `state === "approval-requested" && part.approval.id`
                        // and does not guard `approval`, so a requested part
                        // with the approval object stripped throws on the next
                        // approve click and wedges the run. "output-denied" is
                        // the SDK's terminal state for a call that never got
                        // approval, and it keeps `approval` absent on purpose.
                        const {approval: _dropped, ...rest} = part as Record<
                            string,
                            unknown
                        >;
                        return [{...rest, state: "output-denied"}];
                    }
                    if (
                        isTool &&
                        part.state === "output-available" &&
                        partToolName(part as unknown as Record<string, unknown>) ===
                            ASK_USER_TOOL_NAME &&
                        isQuestionAnswerPayload(
                            (part as { output?: unknown }).output,
                        )
                    ) {
                        // A raw answer payload in an EARLIER message belongs
                        // to a dead run - only the live last message may
                        // carry answers. Left in place, the backend's
                        // resume detection would misread the next send as
                        // an answer to a run that no longer exists, so the
                        // payload is expired to an honest sentence (the
                        // model never saw this answer). This runs for every
                        // flatMap'd message in both modes: sends strip all
                        // but the preserved latest, restores strip all of
                        // them (a paused restore preserves its last message
                        // whole, above).
                        return [
                            {
                                ...part,
                                output:
                                    "The run ended before this answer was " +
                                    "applied; the question went unanswered."}];
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

    // Callbacks that fire outside React's render (Stop, follow, reconnect)
    // need the current session id without re-subscribing on every session
    // switch. It is written by `adoptSession` at the same moment as the
    // state, never by a later effect: a Stop clicked right after a session
    // switch would otherwise address the previous session's run.
    const sessionIdRef = useRef<string | null>(null);
    const adoptSession = useCallback((id: string | null) => {
        sessionIdRef.current = id;
        setSessionId(id);
    }, []);
    // Whether this client is currently subscribed to a run it did not start
    // (after a reload, a tab switch, or a second browser).
    const isFollowingRef = useRef(false);
    // The last settled run this tab has accounted for (reloaded its
    // transcript, reported its failure once): a session key plus a
    // fingerprint of the settled status. ``null`` means the tab has not
    // looked yet; ``fingerprint: ""`` means it has looked and the session
    // was idle-clean at that moment, so any settled run seen later is
    // unambiguously news.
    const settledRunRef = useRef<{ session: string; fingerprint: string } | null>(
        null,
    );

    const {
        messages: uiMessages,
        sendMessage: sdkSendMessage,
        status,
        error,
        setMessages: setUIMessages,
        stop,
        addToolApprovalResponse,
        // Writes a question answer into a tool part's output (matches by
        // toolCallId in any state, rewrites to output-available, then
        // re-evaluates sendAutomaticallyWhen - which resumes the run once
        // every pending part is answered).
        addToolOutput,
        // Follow a run that is still going without sending anything: the GET
        // stream replays the run's journal, so a reload or a second tab
        // rebuilds the same turn.
        resumeStream: sdkResumeStream} = useChat({
        // Recovering a run is this hook's job below, gated on the server's
        // status. The SDK's built-in `resume` recovers only after a network
        // disconnect and would otherwise resume on every mount.
        resume: false,
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
                    // Latest message goes out exactly as the client has it -
                    // steering above all. The old "the newest user message is
                    // what we're sending" reading was wrong once the client
                    // echoed its whole list back: a message typed mid-run
                    // arrives as the SECOND-to-last user message, behind the
                    // assistant turn that is still growing.
                    messages: sanitizeHistory(messages as unknown as unknown[], true),
                    trigger,
                    messageId,
                    sessionId}}),
            // Where a follow request goes. The run lives on the server, so
            // following is a plain GET at that session's stream - never a
            // re-send of the last message.
            prepareReconnectToStreamRequest: () => ({
                api: `${API_BASE}/api/chat/stream?session=${encodeURIComponent(
                    sessionIdRef.current ?? "",
                )}`}),
            // A fresh chat sends no id and the server mints one; the id comes
            // back as a response header, and this is where the client adopts
            // it. Without this the page would keep sending empty ids - each
            // would mint a brand-new session - and Stop/follow would address
            // nothing until a reload. Storing here (not in an effect) keeps
            // the very next send on the same session.
            fetch: async (input, init) => {
                const resp = await fetch(input, init);
                const minted = resp.headers.get("x-berg-session-id");
                if (minted && minted !== sessionIdRef.current) {
                    adoptSession(minted);
                    try {
                        localStorage.setItem(SESSION_ID_KEY, minted);
                    } catch {
                        // Private mode - id stays in memory only.
                    }
                }
                return resp;
            }}),
        // Resume a paused run after approvals or question answers. Both
        // kinds mark their parts one at a time; the resend fires once
        // every pending part in the paused message is answered (stepwise
        // decisions never fire a partial resume, which the backend
        // rejects). Normal finished turns never match:
        // - approvals count as answered in "approval-responded";
        // - a question counts as answered in "output-available" with the
        //   canonical answer payload in its output (see
        //   isQuestionAnswerPayload) - after the resume the server
        //   overwrites that output with the rendered result, which the
        //   shape check rejects, so a completed turn cannot re-fire;
        // - a question counts as waiting in "input-available" (live
        //   wire) and "approval-requested" (a reload's dump marks every
        //   deferred call that way).
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
                const p = part as unknown as Record<string, unknown>;
                const t = typeof p.type === "string" ? p.type : "";
                if (t !== "dynamic-tool" && !t.startsWith("tool-")) continue;
                if (partToolName(p) === ASK_USER_TOOL_NAME) {
                    if (
                        p.state === "output-available" &&
                        isQuestionAnswerPayload(p.output)
                    ) {
                        answered += 1;
                    } else if (
                        p.state === "input-available" ||
                        p.state === "approval-requested"
                    ) {
                        waiting += 1;
                    }
                } else {
                    if (p.state === "approval-responded") answered += 1;
                    else if (p.state === "approval-requested") waiting += 1;
                }
            }
            return answered > 0 && waiting === 0;
        }});

    const isStreaming = status === "streaming" || status === "submitted";

    // Steering the agent has not read yet. This is the queue the transcript
    // cannot show: a message that exists on the server's run but not in the
    // model's view. The server owns the answer, so it is sampled rather than
    // guessed from optimistic sends, and it is empty whenever that is true.
    const [pendingSteering, setPendingSteering] = useState<string[]>([]);
    useEffect(() => {
        if (!sessionId) {
            setPendingSteering([]);
            return;
        }
        let cancelled = false;
        const poll = async () => {
            try {
                const resp = await fetch(
                    `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                );
                if (!resp.ok || cancelled) return;
                const data = (await resp.json()) as {
                    live?: unknown;
                    steering?: unknown;
                };
                // The strip means "the agent is about to read this". Once the
                // run is over nothing will be read in this turn, so the strip
                // empties rather than outliving the run that gave it meaning.
                const queued =
                    data.live === true && Array.isArray(data.steering)
                        ? data.steering.filter(
                              (t): t is string => typeof t === "string",
                          )
                        : [];
                if (!cancelled) setPendingSteering(queued);
            } catch {
                // Backend unreachable - keep showing what we know.
            }
        };
        void poll();
        // Nothing to poll when no run is live; the strip is only ever
        // non-empty inside a run.
        if (!isStreaming) return () => {
            cancelled = true;
        };
        const timer = setInterval(() => void poll(), 1200);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [sessionId, isStreaming]);

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
            const toolName = partToolName(p);
            // Questions have their own card and are answered by tool call
            // id, not approval id; a reloaded run renders them as
            // approval-requested, so they must not leak into this batch.
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
            // A part can be a hole (undefined) after the SDK rewrites
            // the array mid-stream; every field read below is guarded so a
            // sparse entry can never throw inside the render pass.
            const p = part as unknown as Record<string, unknown>;
            if (typeof p !== "object" || p === null) continue;
            if (p.state !== "approval-requested" && p.state !== "approval-responded") {
                continue;
            }
            const approval = p.approval as
                { id?: unknown; approved?: unknown; reason?: unknown } | undefined;
            const approvalId = typeof approval?.id === "string" ? approval.id : null;
            if (!approvalId) continue;
            const toolName = partToolName(p);
            // Same exclusion as pendingApprovals: a question answered
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

    // Full active question batch, mirroring approvalBatch: the LAST
    // assistant message's ask_user_question calls, both pending
    // ("input-available" on the live wire, "approval-requested" after a
    // reload - the dump marks every deferred call that way) and answered
    // (their output holds the canonical payload until the resume fires
    // and the server overwrites it with the rendered result).
    const questionBatch: PendingQuestion[] = [];
    for (let i = uiMessages.length - 1; i >= 0; i--) {
        const msg = uiMessages[i];
        if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
        for (const part of msg.parts) {
            const p = part as unknown as Record<string, unknown>;
            if (typeof p !== "object" || p === null) continue;
            if (partToolName(p) !== ASK_USER_TOOL_NAME) continue;
            const id = typeof p.toolCallId === "string" ? p.toolCallId : null;
            if (!id) continue;
            const answered =
                p.state === "output-available" &&
                isQuestionAnswerPayload(p.output);
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
                answered &&
                (p.output as { cancelled?: unknown }).cancelled === true;
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

    // Answer ONE approval (per-item stepwise decision). The SDK marks
    // that single part as responded; the resume only fires once EVERY
    // pending part in the paused message is answered (see
    // sendAutomaticallyWhen), so partial decisions never trigger a
    // partial resume — the backend requires a complete answer set.
    // Whether the SDK can still resolve an approval id: addToolApprovalResponse
    // matches on a part in state "approval-requested" whose `approval.id`
    // equals the id, and it does not guard `approval` - an id with no such
    // part throws inside the SDK and wedges the run. Every approve path goes
    // through this so the client never asks the SDK to resolve a ghost.
    const approvalResolvable = (id: string) =>
        uiMessages.some((msg) =>
            msg.parts?.some(
                (part) =>
                    typeof part === "object" &&
                    part !== null &&
                    (part as { state?: unknown }).state === "approval-requested" &&
                    (part as { approval?: { id?: unknown } }).approval?.id === id,
            ),
        );

    const respondToApproval = (
        id: string,
        approved: boolean,
        reason?: string,
    ) => {
        if (!approvalResolvable(id)) {
            console.warn(
                `[useAISDKChat] Approval ${id} is not answerable in this message ` +
                    `state (stale or restored run) - ignoring the click.`,
            );
            return;
        }
        void addToolApprovalResponse({id, approved, reason});
    };

    // Answer EVERY pending approval at once (batch convenience).
    const respondToAllApprovals = async (approved: boolean, reason?: string) => {
        const ids = pendingApprovals
            .map((a) => a?.id)
            .filter((id): id is string => Boolean(id) && approvalResolvable(id));
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

    // Answer ONE ask_user_question call. The payload written into the
    // part's output is the canonical wire shape the server's adapter
    // validates against the question that was asked (the harness's
    // check_response): every question answered with labels it offered
    // or a nonblank custom answer, or a bare decline. addToolOutput
    // rewrites the part to output-available and re-evaluates
    // sendAutomaticallyWhen, which resumes the run once every pending
    // part in the paused message is answered.
    const questionResolvable = (id: string) =>
        uiMessages.some((msg) =>
            (msg.parts ?? []).some(
                (part) =>
                    typeof part === "object" &&
                    part !== null &&
                    partToolName(part as unknown as Record<string, unknown>) ===
                        ASK_USER_TOOL_NAME &&
                    (part as unknown as { toolCallId?: unknown }).toolCallId ===
                        id &&
                    !(
                        (part as unknown as { state?: unknown }).state ===
                            "output-available" &&
                        isQuestionAnswerPayload(
                            (part as unknown as { output?: unknown }).output,
                        )
                    ),
            ),
        );

    const respondToQuestion = (
        id: string,
        answers: PendingQuestionAnswer[],
        declined: boolean,
    ) => {
        if (!questionResolvable(id)) {
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
        for (const q of questionBatch) {
            if (!q.answered) respondToQuestion(q.id, [], true);
        }
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
    // A stored snapshot does NOT imply no live run: a reload while the run
    // is paused on an approval restores exactly that. Expiring the pending
    // approval then leaves a paused run the browser can never answer - the
    // card has no Approve button and the turn is wedged. So the server is
    // asked first, and a live pause preserves the approval.
    // Duplicate message ids (e.g. one request dumped to two UI messages)
    // are suffixed — React keys must be unique and ids are otherwise opaque.
    const restoreMessages = useCallback(
        async (msgs: unknown[], sessionId?: string | null) => {
            if (!Array.isArray(msgs)) return;
            let paused = false;
            if (sessionId) {
                try {
                    const resp = await fetch(
                        `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                    );
                    if (resp.ok) {
                        const state = await resp.json();
                        paused = state?.outcome === "paused";
                    }
                } catch {
                    // Status unreachable: fall back to the conservative
                    // "no live run" assumption rather than blocking restore.
                }
            }
            const clean = sanitizeHistory(msgs, paused) as unknown as Array<{
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
        },
        [setUIMessages],
    );

    // Replace the transcript with the server's saved copy of a session.
    // The server owns the conversation, so this is what any client shows
    // once it has stopped following a run: the turn exactly as saved.
    const reloadSession = useCallback(
        async (id: string) => {
            const resp = await fetch(
                `${API_BASE}/api/sessions/${encodeURIComponent(id)}`,
            );
            if (!resp.ok) throw new Error(`Session ${id}: HTTP ${resp.status}`);
            const data = await resp.json();
            await restoreMessages(
                Array.isArray(data.messages) ? data.messages : [],
                id,
            );
            return data;
        },
        [restoreMessages],
    );

    // Open a server-side session: load its transcript, adopt its id.
    const openSession = async (id: string) => {
        const data = await reloadSession(id);
        adoptSession(id);
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
        adoptSession(typeof data.id === "string" ? data.id : null);
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

    // Visible notice for the failure dialog. A failure is transient UI on
    // top of the durable record: the journal text in the transcript is
    // what survives (and reloads); the dialog demands to be read once.
    // Recovery actions the system took (auto-rejected approvals) ride in
    // the notice too, so there is exactly one failure surface.
    const [failureNotice, setFailureNotice] = useState<FailureNotice | null>(
        null,
    );
    // The last user text that was sent, for "Retry last" on a failed
    // send. Updated on every manual send; the retry re-sends it verbatim.
    const lastSentTextRef = useRef<string | null>(null);

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
    // Hard stop on the recovery loop itself. Each auto-reject mints NEW
    // approval ids, so an id set can never bound this: reject → auto-resume →
    // fail → reject again is an unbounded message storm (observed: ~100
    // messages in seconds). After one failed recovery round the loop is
    // disarmed and the next step needs a human send.
    const recoveryRoundsRef = useRef(0);
    useEffect(() => {
        if (!error) {
            // A clean turn in between proves the pipeline works again.
            recoveryRoundsRef.current = 0;
            return;
        }
        if (handledErrorRef.current === error) return;
        handledErrorRef.current = error;
        // A stale deferred answer (HTTP 409) is the designed card-expiry
        // path, not a failure: the run being answered already ended, so
        // there is nothing to diagnose. It must never open the dialog.
        if ((error as {statusCode?: number}).statusCode === 409) return;
        if (recoveryRoundsRef.current >= 1) {
            setFailureNotice({
                kind: "recovery",
                detail: `Send keeps failing (${String(error).slice(0, 160)}).`,
                hint: "Automatic recovery stopped after one round — send a new message to try again."});
            return;
        }
        recoveryRoundsRef.current += 1;
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
        if (ids.length === 0) {
            // The failed send had no approvals to reject. The old behavior
            // silently dropped the error here (nothing surfaced at all);
            // this is exactly the class of failure the dialog is for.
            setFailureNotice({
                kind: "send",
                detail: String(error).slice(0, 300),
                hint: clientFailureHint(String(error))});
            return;
        }
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
        setFailureNotice(
            stopped
                ? {
                      kind: "recovery",
                      detail: "Run stopped — the pending tool approvals were rejected as cleanup.",
                      hint: "Send a message to continue."}
                : {
                      kind: "send",
                      detail: String(error).slice(0, 300),
                      hint: "Its pending approvals were auto-rejected so the conversation can continue — ask the model to retry."},
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
                                await restoreMessages(
                                    data.messages,
                                    storedId,
                                );
                            }
                            adoptSession(storedId);
                            if (data.session && typeof data.session.title === "string") {
                                setSessionTitle(data.session.title);
                            }
                            return;
                        }
                        if (resp.status === 404) {
                            // The stored session is gone (deleted server-side).
                            // Forget it rather than retrying a dead id on every
                            // mount - and so a later send never resurrects it
                            // through the lazy row-create on first message.
                            localStorage.removeItem(SESSION_ID_KEY);
                        }
                    } catch {
                        // Server unreachable - fall through to local cache.
                    }
                } else {
                    // No session yet: adopt the project's active session when one
                    // exists, so every window converges on the same conversation.
                    // With none, the page holds NO id at all and the first send
                    // carries an empty one — the server mints the canonical,
                    // project-suffixed id. A client-side id is the one place a
                    // second id format could reappear, so there is none.
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
                        // Server unreachable - the first send retries.
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

    // A run can outlive this tab (reload, tab switch, second browser) — or
    // start in one while this tab sits idle. While the server reports a
    // run live, this client stays subscribed to it at a tight cadence;
    // when it is not live the watch does NOT stop — it keeps re-asking at
    // a wider cadence, so a run opened in another tab is noticed within
    // one idle poll, and one that started and settled entirely between
    // two polls is still caught: a finished run stays readable for the
    // journal grace window (JOURNAL_GRACE_SECONDS), and its settled
    // status is fingerprinted (boot|generation|outcome|detail). boot is
    // the server process identity — generation restarts with the process,
    // so without boot a fresh process's run #1 could collide with an
    // already-handled run #1 of the previous process and be missed.
    //
    // A settled run is handled exactly once per tab: reload the saved
    // turn, and if it failed open the dialog. The one exception is a
    // settled run that predates this tab's watch of the session — seen on
    // the very first poll, with the tab not following anything — which is
    // adopted silently: a failure that aged in before the tab loaded is
    // history, the transcript already carries the durable ❌ note, and a
    // load must never pop a modal for a run this browser never watched.
    const FOLLOW_POLL_IDLE_MS = 15000;
    const FOLLOW_POLL_LIVE_MS = 3000;
    useEffect(() => {
        if (!sessionId || isStreaming) return;
        // A session switch must not inherit the previous session's watch
        // memory: this tab has not watched anything in the new session yet.
        if (settledRunRef.current && settledRunRef.current.session !== sessionId) {
            settledRunRef.current = null;
            isFollowingRef.current = false;
        }
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const watch = async () => {
            if (cancelled) return;
            let sawLive = false;
            try {
                const resp = await fetch(
                    `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                );
                if (cancelled) return;
                if (resp.ok) {
                    const status = (await resp.json()) as {
                        live?: unknown;
                        boot?: unknown;
                        generation?: unknown;
                        outcome?: unknown;
                        detail?: unknown;
                        hint?: unknown;
                    };
                    if (cancelled) return;
                    if (status.live === true) {
                        // The GET stream replays the run's journal from the
                        // start, so the turn rebuilds exactly as it happened.
                        // A follow that fails must not strand the page: the run
                        // is still live, so the next watch subscribes again.
                        isFollowingRef.current = true;
                        sawLive = true;
                        void sdkResumeStream().catch(() => {
                            // A run can end in the instant between the status
                            // check and the subscribe. The backend answers that
                            // with 204 ("nothing to follow"), which is not an
                            // error; anything else is retried by the next watch,
                            // and the saved transcript is the fallback either way.
                        });
                    } else {
                        // Not live. Two shapes reach here: plain idle (the run
                        // was pruned, or none settled in this server process) or
                        // a settled run still inside the journal grace window,
                        // which carries an outcome.
                        const generation =
                            typeof status.generation === "number"
                                ? status.generation
                                : 0;
                        const outcome =
                            typeof status.outcome === "string" ? status.outcome : null;
                        if (generation === 0 && outcome === null) {
                            if (isFollowingRef.current) {
                                // A followed run whose settled status is gone
                                // entirely: a throttled background tab slept
                                // through the whole grace window. Reload the
                                // transcript it missed.
                                isFollowingRef.current = false;
                                setPendingSteering([]);
                                await reloadSession(sessionId);
                            } else if (settledRunRef.current === null) {
                                // First look at a session with nothing settled:
                                // prime the sentinel so any run that settles
                                // while this tab is open is unmistakably new.
                                settledRunRef.current = {
                                    session: sessionId,
                                    fingerprint: ""};
                            }
                        } else if (outcome !== null) {
                            // A run's settled fingerprint.
                            const fingerprint = [
                                String(status.boot ?? ""),
                                String(status.generation ?? ""),
                                String(status.outcome ?? ""),
                                String(status.detail ?? "").slice(0, 160)].join("|");
                            const known = settledRunRef.current;
                            if (known === null && !isFollowingRef.current) {
                                // The settled run predates this tab's watch of
                                // the session — adopt it without acting.
                                settledRunRef.current = {
                                    session: sessionId,
                                    fingerprint};
                            } else if (
                                known === null ||
                                known.session !== sessionId ||
                                known.fingerprint !== fingerprint
                            ) {
                                // A settled run this tab has not accounted for:
                                // it either followed it to the end or the whole
                                // run happened between two polls. Take the
                                // server's saved turn as the transcript of what
                                // happened — that turn is also where an unread
                                // steer now lives, so the strip empties with
                                // the run it belonged to. A failure is reported
                                // once, here: the journal's failure text is the
                                // record, the dialog is the read-me-once
                                // notice, and the hint comes from the server
                                // (one hint logic, never copied here).
                                if (isFollowingRef.current) {
                                    isFollowingRef.current = false;
                                    setPendingSteering([]);
                                }
                                await reloadSession(sessionId);
                                if (!cancelled) {
                                    settledRunRef.current = {
                                        session: sessionId,
                                        fingerprint};
                                    if (outcome === "failed") {
                                        setFailureNotice({
                                            kind: "run",
                                            detail:
                                                typeof status.detail === "string"
                                                    ? status.detail
                                                    : "",
                                            hint:
                                                typeof status.hint === "string" &&
                                                status.hint
                                                    ? status.hint
                                                    : undefined});
                                    }
                                }
                            }
                        }
                    }
                }
            } catch {
                // Backend unreachable - the next watch retries.
            }
            // Every non-live path (idle, settled, unreadable status) re-arms:
            // the watch is exactly the mechanism that notices a run opened
            // in another tab, and one that stops when no run is live never
            // starts following.
            if (!cancelled) {
                timer = setTimeout(
                    () => void watch(),
                    sawLive ? FOLLOW_POLL_LIVE_MS : FOLLOW_POLL_IDLE_MS,
                );
            }
        };
        void watch();
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [sessionId, isStreaming, sdkResumeStream, reloadSession]);

    // When a run this client SENT ends, check how it ended. A failed run
    // streams its failure text and then closes the SSE stream "cleanly" -
    // the wire never errors - so the browser's own turn can only learn the
    // outcome from the run's status. Without this check the failure would
    // ride the journal text alone and never open the dialog.
    // Fires on the streaming→idle transition only: an old failure seen on
    // mount never pops a modal for a run this browser never watched.
    const ranHereRef = useRef(false);
    useEffect(() => {
        if (isStreaming) {
            ranHereRef.current = true;
            return;
        }
        if (!ranHereRef.current || !sessionId) return;
        ranHereRef.current = false;
        let cancelled = false;
        void (async () => {
            try {
                const resp = await fetch(
                    `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                );
                if (!resp.ok || cancelled) return;
                const s = (await resp.json()) as {
                    outcome?: unknown;
                    detail?: unknown;
                    hint?: unknown;
                };
                if (cancelled || s.outcome !== "failed") return;
                setFailureNotice({
                    kind: "run",
                    detail: typeof s.detail === "string" ? s.detail : "",
                    hint:
                        typeof s.hint === "string" && s.hint
                            ? s.hint
                            : undefined});
            } catch {
                // Status unreachable - the journal text in the transcript
                // is the durable record; the dialog is the transient notice.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [isStreaming, sessionId]);

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
        setFailureNotice(null);
        lastSentTextRef.current = text;
        autoRejectedIds.current.clear();
        void sdkSendMessage({text});
    };

    // Programmatic send (used by App's slash-command handler).
    // Also clears the input box when the sent content matches it.
    const sendMessage = async (content: string) => {
        if (!content.trim() || isStreaming) return;
        setInput((prev) => (prev.trim() === content.trim() ? "" : prev));
        setFailureNotice(null);
        lastSentTextRef.current = content;
        autoRejectedIds.current.clear();
        await sdkSendMessage({text: content});
    };

    // Retry the last user text after a failed send: the words are what
    // the user last chose to say, so "Retry last" must not re-type them
    // by hand. No new failure clears (the next failure replaces), and a
    // retry resets recovery so the auto-reject round is available again.
    const retryLast = () => {
        const text = lastSentTextRef.current;
        if (!text || isStreaming) return;
        setFailureNotice(null);
        autoRejectedIds.current.clear();
        void sdkSendMessage({text});
    };

    // Steer, never interrupt. A message sent while the agent is working joins
    // the run and reaches the model at its NEXT request; the in-flight tool is
    // never aborted. The server decides whether the run is live (it owns the
    // run), so one send path covers both the steer and the fresh turn.
    const steer = async (content: string) => {
        if (!content.trim()) return;
        setInput("");
        setFailureNotice(null);
        await sdkSendMessage({text: content});
    };

    // Stop is an explicit act, and the run no longer belongs to this fetch:
    // aborting the request would only stop *reading* it. So stop tells the
    // server to end the run, then drops the local stream. Everything the run
    // completed is kept (the server persists the turn either way).
    const stopRun = useCallback(() => {
        // Read through the ref: this callback must stop the session that is
        // current NOW, not the one that existed when it was created.
        const id = sessionIdRef.current;
        // An explicit Stop ends the run for good: nothing left to follow.
        isFollowingRef.current = false;
        // And nothing will be read in this turn, so the strip goes with the
        // run. The steer itself is not lost: the server persists it into the
        // turn's record, where the reloaded transcript shows it.
        setPendingSteering([]);
        // Keep the turn up to here - it may hold a steer the model has not
        // read, the approval card, or text already streamed - but mark it
        // closed so it stops looking like it is still being written.
        setUIMessages((msgs) =>
            msgs.map((m) => {
                if (m.role !== "assistant") return m;
                // Not every part kind carries a state; only the ones that
                // stream text, reasoning or tool input do.
                const parts = m.parts.map((p) => {
                    const state = (p as {state?: unknown}).state;
                    return state === "streaming"
                        ? ({...p, state: "done"} as typeof p)
                        : p;
                });
                const changed = parts.some((p, i) => p !== m.parts[i]);
                return changed ? {...m, parts} : m;
            }) as unknown as UIMessage[],
        );
        if (id) {
            void fetch(
                `${API_BASE}/api/chat/stop?session=${encodeURIComponent(id)}`,
                {method: "POST"},
            ).catch(() => {
                // Backend unreachable: the local stop still applies.
            });
        }
        stop();
    }, [stop]);

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
        stop: stopRun,
        sendMessage,
        steer,
        pendingSteering,
        restoreMessages,
        pendingApprovals,
        approvalBatch,
        respondToApproval,
        respondToAllApprovals,
        editApprovalArgs,
        revertApproval,
        questionBatch,
        respondToQuestion,
        declineAllQuestions,
        failureNotice,
        dismissFailureNotice: () => setFailureNotice(null),
        retryLast,
        sessionId,
        sessionTitle,
        newServerChat,
        openSession};
}
