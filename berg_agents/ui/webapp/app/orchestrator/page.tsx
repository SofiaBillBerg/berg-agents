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
 * The orchestrator page — where the user plans WITH the agent.
 *
 * This is the surface the whole TS orchestrator exists for: the user and the
 * orchestrator agree on a shape of work, and the orchestrator delegates to
 * specialists that run as their own durable tasks in berg's Python backend.
 *
 * Deliberately minimal for now. It shows the conversation, the tool activity as
 * it happens, and the workflow run id — because an honest surface tells you
 * which run you are talking to. Rich rendering (specialist cards, gates you
 * answer inline) belongs in a later slice, built on what this proves.
 */

"use client";

import { useState } from "react";

import { useOrchestratorChat } from "@/harness/useOrchestratorChat";

import { Navbar } from "../components/Navbar.tsx";

/**
 * Pull the plain text out of a UI message.
 *
 * @param parts - The message's parts, as the AI SDK holds them.
 * @returns The concatenated text parts.
 */
function textOf(parts: Array<{ type?: string; text?: string }>): string {
    return parts
        .filter((part) => part?.type === "text" && typeof part.text === "string")
        .map((part) => part.text as string)
        .join("");
}

/**
 * List the tool names a message triggered, so delegation is visible.
 *
 * @param parts - The message's parts.
 * @returns One entry per tool part, with its state.
 */
function toolsOf(
    parts: Array<Record<string, unknown>>,
): Array<{name: string, state: string}> {
    return parts
        .filter((part) => String(part?.type ?? "").startsWith("tool-"))
        .map((part) => ({
            // "tool-start_specialist" -> "start_specialist"
            name: String(part.type).replace(/^tool-/, ""),
            // The SDK marks a part as input-available, output-available, etc.
            state: String(part.state ?? "called")}));
}

/**
 * The orchestrator conversation page.
 *
 * @returns The chat surface for the orchestrator.
 */
export default function OrchestratorPage() {
    const {
        messages,
        isStreaming,
        error,
        send,
        stop,
        lastRunId,
        pendingApprovals,
        answerApproval} = useOrchestratorChat();
    const [input, setInput] = useState("");

    /**
     * Send what is in the box, then clear it.
     *
     * @param event - The form submission.
     */
    async function onSubmit(event: React.FormEvent): Promise<void> {
        event.preventDefault();
        const text = input;
        setInput("");
        await send(text);
    }

    return (
        <>
            {/* The nav is rendered per page, not by the root layout (that is how
                app/context/page.tsx and the others do it). Without it this route
                was a bare screen with no way back — reported 2026-11-12. */}
            <Navbar />
            <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
            <header className="flex items-baseline justify-between gap-4">
                <div>
                    <h1 className="text-lg font-semibold">Orchestrator</h1>
                    <p className="text-sm opacity-70">
                        Plan together. It delegates to specialists that run as
                        their own tasks.
                    </p>
                </div>
                {/* The run id is shown, not hidden: it is what identifies this
                    orchestration on a reload or a reconnect. */}
                {lastRunId ? (
                    <code className="text-xs opacity-60" title="workflow run id">
                        {lastRunId}
                    </code>
                ) : null}
            </header>

            <div className="flex-1 space-y-4 overflow-y-auto">
                {messages.length === 0 ? (
                    <p className="text-sm opacity-60">
                        Nothing yet. Ask for something that needs planning, and
                        say what you want to happen.
                    </p>
                ) : null}

                {messages.map((message) => {
                    const parts = message.parts as unknown as Array<
                        Record<string, unknown>
                    >;
                    const text = textOf(parts as never);
                    const tools = toolsOf(parts);
                    const who = message.role === "user" ? "You" : "Orchestrator";

                    return (
                        <div key={message.id} className="space-y-1">
                            <div className="text-xs font-medium opacity-60">
                                {who}
                            </div>
                            {text ? (
                                <div className="whitespace-pre-wrap text-sm">
                                    {text}
                                </div>
                            ) : null}
                            {tools.length > 0 ? (
                                <ul className="space-y-1">
                                    {tools.map((tool, index) => (
                                        <li
                                            key={`${tool.name}-${index}`}
                                            className="rounded border border-current/15 px-2 py-1 text-xs opacity-80"
                                        >
                                            {/* Shown, not summarised away:
                                                delegation is the whole point,
                                                so the user can see it happen. */}
                                            {tool.name}
                                            <span className="opacity-60"> · {tool.state}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : null}
                        </div>
                    );
                })}
            </div>

            {/* The orchestrator's pause, made answerable. Without this the
                run stops and nothing releases it — the agent asks, the user
                decides, and only then does the specialist start or its gate
                open. */}
            {pendingApprovals.length > 0 ? (
                <div className="space-y-2 rounded border border-amber-500/40 p-3">
                    <p className="text-sm font-medium">
                        The orchestrator is waiting on you
                    </p>
                    {pendingApprovals.map((approval) => (
                        <div key={approval.approvalId} className="space-y-1">
                            <p className="text-xs opacity-70">
                                It wants to run{" "}
                                <code className="font-semibold">
                                    {approval.toolName}
                                </code>
                                {approval.input ? (
                                    <span className="opacity-80">
                                        {" "}
                                        —{" "}
                                        {JSON.stringify(
                                            approval.input,
                                        ).slice(0, 300)}
                                    </span>
                                ) : null}
                            </p>
                            <div className="flex gap-2">
                                <button
                                    className="rounded border border-current/30 px-2 py-1 text-xs"
                                    type="button"
                                    onClick={() =>
                                        answerApproval(
                                            approval.approvalId,
                                            true,
                                        )
                                    }
                                >
                                    Allow
                                </button>
                                <button
                                    className="rounded border border-current/30 px-2 py-1 text-xs"
                                    type="button"
                                    onClick={() =>
                                        answerApproval(
                                            approval.approvalId,
                                            false,
                                        )
                                    }
                                >
                                    Refuse
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            ) : null}

            {error ? (
                <p className="rounded border border-red-500/40 p-2 text-sm text-red-500">
                    {error}
                </p>
            ) : null}

            <form className="flex gap-2" onSubmit={onSubmit}>
                <input
                    className="flex-1 rounded border border-current/20 bg-transparent px-3 py-2 text-sm"
                    placeholder="What should we work on?"
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                />
                {isStreaming ? (
                    <button
                        className="rounded border border-current/30 px-3 py-2 text-sm"
                        type="button"
                        onClick={stop}
                    >
                        Stop
                    </button>
                ) : (
                    <button
                        className="rounded border border-current/30 px-3 py-2 text-sm"
                        disabled={!input.trim()}
                        type="submit"
                    >
                        Send
                    </button>
                )}
                </form>
                </div>
            </div>
        </>
    );
}
