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

import { useMemo, useState } from "react";

import { API_BASE } from "@/envConfig";
import { toChatMessage } from "@/harness/messageParts";
import { useOrchestratorChat } from "@/harness/useOrchestratorChat";
import { buildExportMarkdown } from "@/utils/utils";

import AgentSelector from "../components/AgentSelector.tsx";
import { ChatTranscript } from "../components/ChatTranscript.tsx";
import { Navbar } from "../components/Navbar.tsx";
import { PluginCatalog } from "../components/PluginCatalog.tsx";
import { PluginUISurface } from "../plugins/PluginUISurface.tsx";
import { ProviderSelector } from "../components/ProviderSelector.tsx";
import { usePluginSurface } from "../hooks/usePluginSurface";

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

    // The same side-surface machinery the chat page uses — one hook, so todos
    // and plugin surfaces behave identically here. It wants berg's ChatMessage
    // shape, and the orchestrator speaks UIMessage, so the transcript is
    // converted at this boundary (`toChatMessage`) rather than teaching the
    // hook a second message type.
    const chatMessages = useMemo(
        () => messages.map((message) => toChatMessage(message)),
        [messages],
    );
    const {
        sidePluginId,
        setSidePluginId,
        showCatalog,
        setShowCatalog,
        pluginView,
        setPluginView,
        sideWidth,
        setSideWidth,
        sideDragging,
        startSideDrag,
        pluginSurfaces,
        activeSurface,
        pluginRefreshKey,
        pluginCount,
        setPluginCount} = usePluginSurface({apiBase: API_BASE, messages: chatMessages});

    /**
     * Download the conversation as markdown.
     *
     * Uses the same `buildExportMarkdown` the chat page uses, fed the
     * orchestrator's transcript in its `ChatMessage` shape, so an export from
     * either surface reads the same.
     */
    function exportTranscript(): void {
        // Large transcripts are multi-megabyte blobs: the object URL must
        // outlive the click, so revocation is deferred rather than immediate.
        const markdown = buildExportMarkdown(chatMessages, [], null, null);
        const blob = new Blob([markdown], {type: "text/markdown"});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `berg-orchestrator-${new Date()
            .toISOString()
            .slice(0, 10)}.md`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    }

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

                    {/* The same controls the chat page offers, because the
                        orchestrator is where planning happens: which model,
                        which agent, whose todos, which plugins. Reused rather
                        than reimplemented — these are the real components. */}
                    <div className="flex flex-wrap items-center gap-2">
                        {pluginSurfaces.map((surface) => {
                            const isOpen = sidePluginId === surface.pluginId;
                            const label =
                                (surface.ui?.label as string | undefined) ??
                                surface.pluginId;
                            return (
                                <button
                                    key={surface.pluginId}
                                    className="rounded border border-current/30 px-2 py-1 text-xs"
                                    type="button"
                                    onClick={() => {
                                        setShowCatalog(false);
                                        setSidePluginId(
                                            isOpen ? null : surface.pluginId,
                                        );
                                    }}
                                >
                                    {label}
                                    {isOpen && pluginCount > 0
                                        ? ` (${pluginCount})`
                                        : ""}
                                </button>
                            );
                        })}
                        <button
                            aria-label={
                                showCatalog ? "Hide plugins" : "Show plugins"
                            }
                            className="rounded border border-current/30 px-2 py-1 text-xs"
                            type="button"
                            onClick={() => {
                                setShowCatalog((prev) => !prev);
                                setSidePluginId(null);
                            }}
                        >
                            🔌 Plugins
                        </button>
                        <span className="flex-1" />
                        <AgentSelector />
                        <ProviderSelector />
                        <button
                            className="rounded border border-current/30 px-2 py-1 text-xs"
                            type="button"
                            onClick={exportTranscript}
                        >
                            ⬇ Export
                        </button>
                    </div>

                    {/* Transcript and side surface side by side, exactly as
                        the chat page lays them out: the transcript keeps its
                        own flex column so heights match, and a drag divider
                        lets the surface be widened. */}
                    <div className="mb-2 flex min-h-0 flex-1 gap-0">
                    <div className="flex min-w-0 flex-1 flex-col">
                        {/* The real transcript, not a reimplementation: it is
                            what gives chat its Streamdown rendering (markdown,
                            mermaid, code highlighting), collapsible tool cards
                            and reasoning traces. The orchestrator was showing
                            raw text before — the same words with none of the
                            reading (reported 2026-11-12 from a side-by-side
                            screenshot with the chat page). */}
                        <ChatTranscript
                            hitlRequest={undefined}
                            isAnimating={isStreaming}
                            isExecuting={isStreaming}
                            transcript={chatMessages}
                        />
                    </div>

                    {sidePluginId !== null || showCatalog ? (
                        <>
                            <div
                                aria-orientation="vertical"
                                aria-valuemax={Math.max(320, 1200)}
                                aria-valuemin={280}
                                aria-valuenow={sideWidth}
                                className={`w-1 shrink-0 cursor-col-resize rounded bg-border transition-colors hover:bg-primary ${
                                    sideDragging ? "bg-primary" : ""
                                }`}
                                role="separator"
                                tabIndex={0}
                                onKeyDown={(event) => {
                                    if (event.key === "ArrowLeft")
                                        setSideWidth((width) =>
                                            Math.min(
                                                Math.max(
                                                    320,
                                                    window.innerWidth - 420,
                                                ),
                                                width + 24,
                                            ),
                                        );
                                    if (event.key === "ArrowRight")
                                        setSideWidth((width) =>
                                            Math.max(280, width - 24),
                                        );
                                }}
                                onPointerDown={startSideDrag}
                            />
                            {sidePluginId && activeSurface ? (
                                <PluginUISurface
                                    key={sidePluginId}
                                    className={
                                        pluginView === "canvas"
                                            ? "flex-1"
                                            : "shrink-0"
                                    }
                                    pluginId={sidePluginId}
                                    refreshKey={pluginRefreshKey}
                                    style={
                                        pluginView === "canvas"
                                            ? undefined
                                            : {width: sideWidth}
                                    }
                                    ui={activeSurface.ui}
                                    view={pluginView}
                                    onClose={() => setSidePluginId(null)}
                                    onCount={setPluginCount}
                                    onToggleView={() =>
                                        setPluginView((view) =>
                                            view === "panel"
                                                ? "canvas"
                                                : "panel",
                                        )
                                    }
                                />
                            ) : (
                                <PluginCatalog
                                    className="shrink-0"
                                    style={{width: sideWidth}}
                                    onClose={() => setShowCatalog(false)}
                                />
                            )}
                        </>
                    ) : null}
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
