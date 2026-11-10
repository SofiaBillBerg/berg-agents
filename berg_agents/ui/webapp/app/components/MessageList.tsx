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

import type {ChatMessage, MessageToolCall} from "@/harness";

import {useEffect, useMemo, useState} from "react";
import {Button, Surface} from "@heroui/react";

import {MarkdownRenderer} from "./MarkdownRenderer.tsx";
import {ToolCard} from "./ToolCard.tsx";
import DelegationTaskControls from "./DelegationTaskControls.tsx";

import {fetchPlugins} from "@/lib/backendCatalog";

/** Plugin tool names, supplied by the backend (see usePluginSurfaceTools). */
const PLUGIN_SURFACE_TOOLS = new Set<string>();

/**
 * Track which tool names belong to a plugin surface.
 *
 * The backend is the only place that knows which plugins are
 * installed, so the host asks it rather than keeping its own list.
 * Until it answers the marker stays neutral — never wrong.
 */
export function usePluginSurfaceTools(): void {
    useEffect(() => {
        let cancelled = false;
        // The backend is the only place that knows which tools belong to a
        // plugin surface, and it is asked through the shared catalog client
        // (one request for every reader in the app).
        void fetchPlugins().then((plugins) => {
            if (cancelled) return;
            PLUGIN_SURFACE_TOOLS.clear();
            for (const p of plugins) {
                if (p && Array.isArray(p.tools)) {
                    for (const t of p.tools) {
                        if (typeof t === "string") PLUGIN_SURFACE_TOOLS.add(t);
                    }
                }
            }
        });
        return () => {
            cancelled = true;
        };
         
    }, []);
}

/**
 * The transcript this component renders. The shape is the harness's own
 * `ChatMessage` — the copy that used to live here had already drifted
 * from it (it knew nothing of a tool call's `children`), and one shape
 * for one message is the rule.
 */
export interface MessageListProps {
    history?: ChatMessage[];
    /** Whether the assistant turn is currently streaming (animates code blocks). */
    isAnimating?: boolean;
    /** Answer a delegated task's gated write. Absent means the caller has
        no such surface (export, tests), and the buttons are not drawn. */
    onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
}

/**
 * Collapsible reasoning trace for one assistant message.
 * The model's chain-of-thought streams in as `reasoning` parts;
 * shown open by default so the reasoning stays visible (cumulative) as it
 * lands and after the turn completes. Collapse it with the button to read
 * back through history.
 */
function ReasoningBlock({
    text,
    isAnimating}: {
    text: string;
    /** Whether the turn is still streaming (keeps thinking open). */
    isAnimating?: boolean;
}) {
    const [open, setOpen] = useState(true);
    return (
        <div className="reasoning-block mt-1">
            <button
                aria-label={open ? "Hide reasoning" : "Show reasoning"}
                className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                onClick={() => setOpen((prev) => !prev)}
            >
                {open ? "🧠 Hide thinking" : "🧠 Show thinking"}
            </button>
            {open && (
                <div className="mt-1 border-l-2 border-accent/40 pl-2 text-xs text-muted-foreground">
                    <MarkdownRenderer content={text} isAnimating={isAnimating}/>
                </div>
            )}
        </div>
    );
}

/**
 * One assistant turn's tool calls as a single collapsible group.
 * A lone call or two stays open so progress reads inline; a longer
 * batch starts collapsed so the answer above it stays followable.
 * Each call keeps its own Show/Hide + Copy inside.
 */
function ToolCallGroup({
                            calls,
                            isAnimating,
                            onResolveDelegatedApproval}: {
    calls: NonNullable<ChatMessage["toolCalls"]>;
    /** Keep the group open while the turn is still streaming. */
    isAnimating?: boolean;
    onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
}) {
    const [open, setOpen] = useState(true);
    // NOTE: Plugin tool calls render under their own marker so todo
    // activity reads as plugin work, not generic tool output. The full
    // interactive surface lives in the side-panel/canvas (TodoPanel).
    const isTodoGroup =
        calls.length > 0 && calls.every((c) => PLUGIN_SURFACE_TOOLS.has(c.tool));
    return (
        <div className="mt-1.5 flex flex-col gap-1 rounded-md border border-border px-1.5 py-1">
            <button
                aria-label={
                    open
                        ? `Collapse ${calls.length} tool calls`
                        : `Expand ${calls.length} tool calls`
                }
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                type="button"
                onClick={() => setOpen((prev) => !prev)}
            >
                <span aria-hidden>{open ? "▾" : "▸"}</span>
                <span className="font-mono">
          {isTodoGroup ? "📋" : "🔧"} {calls.length} tool call
                    {calls.length === 1 ? "" : "s"}
        </span>
                <span className="truncate text-[11px]">
          {calls.map((c) => c.tool).join(", ")}
        </span>
                {isAnimating && (
                    <span className="ml-1 text-[10px] text-muted-foreground animate-pulse">
                        streaming
                    </span>
                )}
            </button>
            {open && (
                <div className="flex flex-col gap-1">
                    {calls.map((call, callIdx) => (
                        <div key={`tool-${callIdx}-${call.tool}`} className="flex flex-col gap-1">
                            <ToolCard
                                expanded={false}
                                input={call.input}
                                output={call.output}
                                state={call.state}
                                tool={call.tool}
                            />
                            {/* A delegated subagent's own streamed work:
                                its text and tool calls, nested inside the
                                call they ran under rather than beside it. */}
                            {call.children && (
                                <SubagentWork
                                    isAnimating={isAnimating}
                                    parts={call.children}
                                    onResolveDelegatedApproval={
                                        onResolveDelegatedApproval
                                    }
                                />
                            )}
                            {/* Steering and stopping that task, while it
                                is still running: the controls sit with the
                                work they act on, not in the chrome. */}
                            {call.delegatedTask && (
                                <DelegationTaskControls
                                    task={call.delegatedTask}
                                />
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

/**
 * One subagent's streamed work, rendered under the tool call it ran in.
 *
 * The relay brackets a delegated run so these parts can be attributed to
 * that call; this is what makes a delegate inspectable - the implementer's
 * own file reads, writes and text, inside the `implement_task` card.
 */
function SubagentWork({
    parts,
    isAnimating,
    onResolveDelegatedApproval}: {
    parts: NonNullable<MessageToolCall["children"]>;
    /** Whether the turn is still streaming (thinking shown open by default). */
    isAnimating?: boolean;
    onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
}) {
    return (
        <div
            aria-label="Work done inside this tool call"
            className="ml-2 flex flex-col gap-1 border-l-2 border-accent/40 pl-2"
            role="group"
        >
            {parts.reasoning && <ReasoningBlock isAnimating={isAnimating} text={parts.reasoning}/>}
            {parts.text && (
                <div className="text-xs text-muted-foreground">
                    <MarkdownRenderer content={parts.text} isAnimating={isAnimating}/>
                </div>
            )}
            {parts.toolCalls && parts.toolCalls.length > 0 && (
                <ToolCallGroup calls={parts.toolCalls} isAnimating={isAnimating}/>
            )}
            {/* A delegated task's gated write, decided in place. It sits
                with the work it belongs to rather than in the run's
                approval batch, which cannot answer it. */}
            {onResolveDelegatedApproval &&
                (parts.toolCalls ?? [])
                    .filter((c) => c.state === "approval-requested")
                    .filter((c) => Boolean(c.toolCallId))
                    .map((call) => (
                        <div
                            key={`delegated-approval-${call.toolCallId}`}
                            className="flex flex-wrap items-center gap-2 rounded-md border border-warning p-1.5"
                        >
                            <span className="text-xs">
                                ⏳ {call.tool} needs your approval
                                {call.input ? ` (${call.input})` : ""}
                            </span>
                            <Button
                                isDisabled={false}
                                size="sm"
                                variant="primary"
                                onPress={() =>
                                    onResolveDelegatedApproval(
                                        call.toolCallId as string,
                                        true,
                                    )
                                }
                            >
                                ✅ Approve
                            </Button>
                            <Button
                                isDisabled={false}
                                size="sm"
                                variant="secondary"
                                onPress={() =>
                                    onResolveDelegatedApproval(
                                        call.toolCallId as string,
                                        false,
                                    )
                                }
                            >
                                ❌ Reject
                            </Button>
                        </div>
                    ))}
        </div>
    );
}

/**
 * MessageList component.
 * Renders conversation transcript messages with Markdown rendering.
 *
 * @param props - Component properties
 * @returns JSX element rendering the messages list
 */
export function MessageList({
                                  history = [],
                                  isAnimating,
                                  onResolveDelegatedApproval}: MessageListProps) {
    usePluginSurfaceTools();

    /**
     * Merge consecutive assistant messages into one display group so that
     * tool calls the backend split across several protocol messages render
     * under a single header instead of one block per call. The merge is
     * display-only: message ids, tool-call ids and approval state are kept
     * per-call so HITL / delegation handling is untouched.
     */
    const groups = useMemo(() => {
        const out: Array<{kind: "single" | "group"; messages: ChatMessage[]}> = [];
        let cur: ChatMessage[] | null = null;
        const push = (buf: ChatMessage[]) => {
            if (buf.length === 0) return;
            if (buf.length === 1) out.push({kind: "single", messages: buf});
            else out.push({kind: "group", messages: buf});
        };
        for (const msg of history) {
            if (msg.role === "assistant") {
                if (cur === null) cur = [msg];
                else cur.push(msg);
            } else {
                push(cur ?? []);
                cur = null;
                out.push({kind: "single", messages: [msg]});
            }
        }
        push(cur ?? []);
        return out;
    }, [history]);

    return (
        <div
            aria-label="Conversation transcript"
            className="message-list flex flex-col gap-2"
            role="log"
        >
            {groups.map((g, gi) => {
                const assistant = g.kind === "group"
                    ? g.messages
                    : g.messages[0].role === "assistant"
                        ? g.messages
                        : null;
                const isGroup = g.kind === "group" && !!assistant;
                const role = isGroup ? "assistant" : g.messages[0].role;
                const roleClass =
                    role === "user"
                        ? "message-role-user"
                        : role === "system"
                            ? "message-role-system"
                            : "message-role-agent";
                const roleLabel =
                    role === "user"
                        ? "User"
                        : role === "system"
                            ? "System"
                            : "Agent";
                const text = assistant ? assistant.map((m) => m.content).filter(Boolean).join("\n") : g.messages[0].content;
                const reasoning = assistant ? assistant.map((m) => m.reasoning).filter(Boolean).join("\n") : g.messages[0].reasoning;
                const toolCalls = isGroup
                    ? ([] as ChatMessage["toolCalls"]).concat(...g.messages.map((m) => m.toolCalls ?? []))
                    : g.messages[0].toolCalls;
                return (
                    <Surface
                        key={`msg-${gi}-${isGroup ? "group" : g.messages[0].id ?? gi}`}
                        className={`message-list-item px-2.5 py-2 ${roleClass}`}
                        variant="secondary"
                    >
                        <div className="text-xs font-semibold tracking-wide uppercase text-muted mb-1">
                            {roleLabel}
                        </div>
                        {reasoning && <ReasoningBlock isAnimating={isAnimating} text={reasoning}/>}
                        <div className="message-list-content text-sm">
                            <MarkdownRenderer
                                content={text}
                                isAnimating={role === "assistant" && isAnimating}
                            />
                        </div>
                        {toolCalls && toolCalls.length > 0 && (
                            <ToolCallGroup
                                    calls={toolCalls}
                                    isAnimating={isAnimating}
                                    onResolveDelegatedApproval={
                                        onResolveDelegatedApproval
                                    }
                                />
                        )}
                    </Surface>
                );
            })}
        </div>
    );
}

export default MessageList;
