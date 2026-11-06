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
 * One walk over a UIMessage's parts - the single derivation of what the
 * transcript shows.
 *
 * The chat UI renders three things from the raw protocol parts: the
 * visible text, the model's reasoning trace, and the tool calls as
 * cards. Those used to be three separate loops over the same array, so
 * every new part kind (a nested subagent stream above all) had to be
 * taught to all three or it silently vanished from one of them. There
 * is now one loop that fills all three in a single pass, and this module
 * is the only place that knows the part shapes.
 *
 * The UI-facing message shape lives here too: what the components render
 * is exactly what these functions produce.
 */

import type {TextUIPart, UIMessage} from "ai";

import {ASK_USER_TOOL_NAME} from "./askUser";

/** Max output chars kept per tool call for display/export. */
const MAX_TOOL_OUTPUT_CHARS = 4000;

/** The UI-facing shape of one transcript message. */
export interface ChatMessage {
    id: string;
    role: "user" | "assistant" | "system";
    content: string;
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

/** What one pass over a message's parts yields. */
export interface MessageParts {
    /** Visible transcript: text parts plus a marker per in-flight call. */
    text: string;
    /** Reasoning trace, or undefined when the model produced none. */
    reasoning?: string;
    /** Every tool call (in flight and finished), or undefined when none. */
    toolCalls?: ChatMessage["toolCalls"];
}

/**
 * Read a tool part's wire name. Typed parts carry it in the `type` prefix
 * (`tool-<name>`); a part the client normalized to a dynamic tool carries a
 * separate `toolName` field instead. One derivation for every call site.
 *
 * @param p - One part as an untyped record.
 * @returns The tool name, or "tool" when the part carries neither form.
 */
export function partToolName(p: Record<string, unknown>): string {
    const type = typeof p.type === "string" ? p.type : "";
    return (
        (typeof p.toolName === "string" && p.toolName) ||
        (type.startsWith("tool-") ? type.slice("tool-".length) : "tool")
    );
}

/**
 * Render a tool call's arguments as `key=value` pairs for a one-line
 * marker. Objects only: a raw string input has no pairs to show.
 *
 * @param input - The tool part's `input` field.
 * @returns `(k=v, ...)`, or an empty string when there is nothing to show.
 */
function toolArgsSnippet(input: unknown): string {
    if (input == null || typeof input !== "object") return "";
    try {
        const entries = Object.entries(input as Record<string, unknown>).map(
            ([k, v]) => {
                const s = typeof v === "string" ? v : JSON.stringify(v);
                return `${k}=${s}`;
            },
        );
        return entries.length > 0 ? `(${entries.join(", ")})` : "";
    } catch {
        return "";
    }
}

/**
 * Walk one message's parts once, filling text, reasoning and tool calls.
 *
 * Part kinds, in the order the protocol emits them:
 * - `text` - the visible answer. In` blocks are lifted
 *   out into `reasoning` and stripped from the text, so both flavors
 *   (a typed thinking part, and qwen-style inline thinking) land in the
 *   same collapsed trace instead of leaking into the answer.
 * - `reasoning` / `thinking*` - the model's chain-of-thought.
 * - `tool-<name>` / `dynamic-tool` - one tool call. Finished calls
 *   (those with an output) render as collapsible cards downstream, so
 *   the text transcript carries only a marker for calls still in flight
 *   or awaiting a decision, rendered by kind: a question reads as "the
 *   model is asking", an approval as "waiting for you", and a part
 *   without an approval id as expired (a ghost from a dead run).
 *
 * @param msg - The AI SDK message to read.
 * @returns The three renderings, any of them empty when absent.
 */
export function readMessageParts(msg: UIMessage): MessageParts {
    const textChunks: string[] = [];
    const reasoningBits: string[] = [];
    const toolCalls: NonNullable<ChatMessage["toolCalls"]> = [];

    for (const part of msg.parts) {
        if (typeof part !== "object" || part === null) continue;
        const p = part as unknown as Record<string, unknown>;
        const pType = typeof p.type === "string" ? p.type : "";

        // Reasoning: a typed part from one provider, an inline
        // <think> block from another. Both become the same trace.
        if (
            pType === "reasoning" ||
            pType.startsWith("thinking") ||
            pType.startsWith("reasoning")
        ) {
            const text =
                (typeof p.text === "string" && p.text) ||
                (typeof p.reasoning === "string" && p.reasoning) ||
                "";
            if (text.trim() !== "") reasoningBits.push(text);
            continue;
        }

        if (pType === "text") {
            const raw = (part as unknown as TextUIPart).text;
            const source = typeof raw === "string" ? raw : "";
            // Inline thinking first: the block belongs to `reasoning`,
            // never to the answer.
            const matches = source.match(/<think>([\s\S]*?)(?:<\/think>|$)/gi);
            if (matches) {
                for (const m of matches) {
                    const inner = m
                        .replace(/<\/?think>/gi, "")
                        .trim();
                    if (inner) reasoningBits.push(inner);
                }
            }
            // Then the visible text, with those blocks removed.
            const cleaned = source
                .replace(/<think>[\s\S]*?<\/think>/gi, "")
                .replace(/<\/?think>/gi, "")
                .trim();
            if (cleaned) textChunks.push(cleaned);
            continue;
        }

        // Tool parts: `dynamic-tool` or `tool-<name>` shapes (v7).
        if (pType === "dynamic-tool" || pType.startsWith("tool-")) {
            const name = partToolName(p);
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
            const raw = (p as {output?: unknown}).output;
            if (raw !== undefined && raw !== null) {
                try {
                    output =
                        typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
                } catch {
                    output = String(raw);
                }
                if (output.length > MAX_TOOL_OUTPUT_CHARS) {
                    output = `${output.slice(0, MAX_TOOL_OUTPUT_CHARS)}\n… (output truncated)`;
                }
            }
            toolCalls.push({
                tool: name,
                input: input || undefined,
                output,
                state: typeof p.state === "string" ? (p.state as string) : undefined});

            // A call still in flight or awaiting a decision: the card
            // downstream has no output to show, so the transcript keeps
            // a one-line marker for it.
            if (output === undefined) {
                const approval = (p as {approval?: unknown}).approval as
                    | {id?: unknown}
                    | undefined;
                const marker =
                    name === ASK_USER_TOOL_NAME
                        ? "❓ question pending"
                        : (p as {state?: unknown}).state === "approval-requested"
                          ? typeof approval?.id === "string"
                              ? "⏳ needs approval"
                              : "⏳ approval expired"
                          : "🔧";
                textChunks.push(`${marker} ${name}${toolArgsSnippet(p.input)}`);
            }
        }
    }

    return {
        // Double newline: react-markdown renders a single \n as a space,
        // so separate text parts (e.g. the implementer's progress lines)
        // would otherwise collapse onto one line.
        text: textChunks.filter(Boolean).join("\n\n"),
        reasoning: reasoningBits.length > 0 ? reasoningBits.join("\n") : undefined,
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined};
}

/**
 * Build the UI-facing message the transcript renders from one raw
 * protocol message.
 *
 * @param msg - The AI SDK message to convert.
 * @returns The ChatMessage for the transcript.
 */
export function toChatMessage(msg: UIMessage): ChatMessage {
    const {text, reasoning, toolCalls} = readMessageParts(msg);
    return {
        id: msg.id,
        role: msg.role as ChatMessage["role"],
        content: text,
        reasoning,
        toolCalls};
}
