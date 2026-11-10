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
 * App component - uses AI SDK v7's useChat hook directly via useAISDKChat.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. The frontend uses useChat from
 * @ai-sdk/react to consume it.
 */

import type { Command } from "./components/SlashCommandAutocomplete";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Toast, toast } from "@heroui/react";
import { useRouter } from "next/navigation";

import { SlashCommandAutocomplete } from "./components/SlashCommandAutocomplete";
import InputBar from "./components/InputBar.tsx";
import SteeringStrip from "./components/SteeringStrip.tsx";
import ContextGauge from "./components/ContextGauge.tsx";
import ApprovalItem from "./components/ApprovalItem";
import QuestionItem from "./components/QuestionItem";
import DelegationQuestionCard from "./components/DelegationQuestionCard";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import AgentSelector from "./components/AgentSelector.tsx";
import RouterStatsPanel from "./components/RouterStatsPanel.tsx";
import ChatTranscript, {
  CHAT_SCROLL_ID} from "./components/ChatTranscript.tsx";
import FailureDialog from "./components/FailureDialog";
import { PluginUISurface } from "./plugins/PluginUISurface.tsx";
import { PluginCatalog } from "./components/PluginCatalog.tsx";
import Navbar from "./components/Navbar.tsx";
import { setRuntimeSessionId } from "./runtime/berg-runtime.ts";
import { useBackendCatalog } from "./hooks/useBackendCatalog";
import { usePluginSurface } from "./hooks/usePluginSurface";
import { useSlashCommands } from "./hooks/useSlashCommands";

import { buildExportMarkdown } from "@/utils/utils";
import { API_BASE } from "@/envConfig";
import { useAISDKChat } from "@/harness";

/*
 * Error boundary for lazy-loaded components.
 */
class LazyComponentErrorBoundary extends React.Component<
  { children: React.ReactNode; componentName: string },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode; componentName: string }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(
      `${this.props.componentName} failed to load:`,
      error,
      errorInfo,
    );
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card className="m-4 border-danger" variant="default">
          <Card.Header>
            <Card.Title className="text-danger">
              Failed to load {this.props.componentName}
            </Card.Title>
          </Card.Header>
          <Card.Content>
            <p className="text-sm">
              The {this.props.componentName} component encountered an error.
            </p>
            <pre className="text-xs mt-2 bg-surface-tint p-2 rounded">
              {this.state.error?.message}
            </pre>
          </Card.Content>
        </Card>
      );
    }
    return this.props.children;
  }
}

/*
 * Main chat UI - receives state from useAISDKChat and renders the interface.
 */
function ChatContent() {
  const router = useRouter();
  const aiChat = useAISDKChat();
  const {
    messages,
    input,
    setInput,
    isStreaming,
    error: chatError,
    sendMessage,
    stop,
    clearMessages,
    restoreMessages,
    steer,
    pendingSteering,
    approvalBatch,
    respondToApproval,
    respondToAllApprovals,
    resolveDelegatedApproval,
    editApprovalArgs,
    revertApproval,
    questionBatch,
    respondToQuestion,
    declineAllQuestions,
    delegationQuestions,
    answerDelegation,
    failureNotice,
    dismissFailureNotice,
    retryLast,
    sessionId,
    sessionTitle,
    newServerChat,
    openSession} = aiChat;
  // The backend's three catalogs (tools, agents, router stats) - one
  // reader each, in ./hooks/useBackendCatalog.
  const { backendTools, agents, routerStats } = useBackendCatalog({
    apiBase: API_BASE});

  // Publish the active session to plugin surfaces (via window.BergRuntime).
  // A plugin whose storage is per session reads this to name the store it
  // writes to; without it the panel would write to a store no session owns
  // and show a different plan than the model.
  useEffect(() => {
    setRuntimeSessionId(aiChat.sessionId ?? "");
  }, [aiChat.sessionId]);

  // Commands for the slash-autocomplete palette
  const localCommands: Command[] = [
    ...backendTools.map((t) => ({
      name: `/${t.name}`,
      description: t.description})),
    { name: "/help", description: "Show help info" },
    { name: "/agents", description: "List available agents" },
    { name: "/stats", description: "Show stats" },
    { name: "/clear", description: "Clear chat history" },
    { name: "/memory", description: "Show shared memory files" },
    { name: "/skills", description: "List agent skills" },
    { name: "/mcps", description: "Show MCP server status" },
    { name: "/exit", description: "Exit chat" },
    { name: "/read_file", description: "Read a file via the backend" },
    { name: "/list_files", description: "List a directory via the backend" }];

  // Total questions across the active question batch (one call can carry
  // several), for the question card's header copy.
  const questionCount = questionBatch.reduce(
    (n, q) => n + Math.max(q.questions.length, 1),
    0,
  );

  // Slash commands - the local answers, the cards they land in, and the
  // auto-approve opt-in - live in ./hooks/useSlashCommands.
  const {
    autoApproveEdits,
    toggleAutoApproveEdits,
    toolResults,
    cmdCards,
    addCmdCard,
    dismissCmdCard,
    processSlashCommand} = useSlashCommands({
    apiBase: API_BASE,
    backendTools,
    agents,
    routerStats,
    sendMessage,
    clearMessages,
    sessionId,
    openSession,
    messages,
    input,
    approvalBatch,
    respondToAllApprovals});

  // -------------------------------------------------------------------------
  // Sessions + conversation navigation
  // -------------------------------------------------------------------------
  /** Show/hide the inline Details & Activity panel. */
  const [showDetails, setShowDetails] = useState(false);

  // Plugin surfaces: the whole machine - which surface is open, how it
  // is presented, how wide, when it re-fetches - lives in
  // ./hooks/usePluginSurface.
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
    setPluginCount} = usePluginSurface({ apiBase: API_BASE, messages });

  /** Scroll the transcript (the page itself never scrolls). */
  const scrollChatTo = (where: "top" | "bottom") => {
    const el = document.getElementById(CHAT_SCROLL_ID);
    if (!el) return;
    el.scrollTo({ top: where === "top" ? 0 : el.scrollHeight });
  };

  /** Park the live chat as a resumable session, then start fresh. */
  const startNewChat = () => {
    stop();
    // NOTE: Server session first (numbered title); local clear only
    // when the backend is unreachable.
    void newServerChat().catch(() => clearMessages());
  };

  /*
   * Execute a tool via the backend /api/tool/execute endpoint.
   *
   * The backend is expected to accept a JSON payload:
   *   { tool: string, args: any }
   * and to respond with a JSON object that contains at least an `output` field
   * (the result of the tool).  Adjust the URL / payload shape to match your
   * actual API.
   */

  // -------------------------------------------------------------------------
  // Send handler - intercepts slash commands, otherwise forwards to AI SDK.
  // While a run is live, sending steers it: the message reaches the model at
  // its next request and nothing in flight is aborted. Otherwise it sends a
  // fresh turn.
  // -------------------------------------------------------------------------
  const forwardToModel = useCallback(
    (text: string) => {
      if (isStreaming) {
        void steer(text);
      } else {
        void sendMessage(text);
      }
    },
    [isStreaming, steer, sendMessage],
  );

  // Guards double submits (fast double-Enter / Enter+click fired two
  // identical POSTs before streaming state flipped). Released shortly
  // after; streaming state (or the interrupt path) owns re-entry
  // protection from there on.
  const sendGuardRef = useRef<string | null>(null);

  const handleSendWrapper = useCallback(() => {
    if (!input.trim()) return;
    if (sendGuardRef.current === input.trim()) return;
    sendGuardRef.current = input.trim();
    setTimeout(() => {
      sendGuardRef.current = null;
    }, 1500);

    // Detect a leading slash command.
    const cmdMatch = input.trim().match(/^\/(\w+)\s*(.*)/);
    if (cmdMatch) {
      void processSlashCommand(input.trim()).then((outcome) => {
        if (!outcome.handled) {
          // Not a recognized command - forward the original text.
          forwardToModel(input.trim());
          return;
        }
        // Handled: clear the box and surface the answer card (if any)
        // above the transcript. Without this the card is dropped and
        // every slash command looks like a no-op.
        setInput("");
        if (outcome.card) addCmdCard(outcome.card);
      });
      return;
    }

    // No slash prefix - just send the message to the AI model.
    forwardToModel(input.trim());
  }, [input, processSlashCommand, forwardToModel]);

  // -------------------------------------------------------------------------
  // Keyboard handling (Enter → send, Shift+Enter → new line)
  // -------------------------------------------------------------------------
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendWrapper();
      }
    },
    [handleSendWrapper],
  );

  // Client send failures no longer toast: the FailureDialog is the one
  // failure surface (modal, dismiss-when-read, with hint + Retry). The
  // raw error text stays visible in the Details panel below, so a
  // dismissed dialog never loses the information.

  // -------------------------------------------------------------------------
  // Status determination (error / streaming / idle)
  // -------------------------------------------------------------------------
  const statusInfo = chatError
    ? { label: "Error", color: "var(--berg-status-error)", pulse: false }
    : isStreaming
      ? {
          label: "Thinking...",
          color: "var(--berg-status-info)",
          pulse: true}
      : { label: "Idle", color: "var(--berg-muted)", pulse: false };

  return (
    <LazyComponentErrorBoundary componentName="Chat">
      <Toast.Provider />
      <Navbar />
      <div className="app-container p-4 w-full max-w-[95vw] mx-auto">
        {/* Single chrome row: title + sessions + nav + provider + export.
            One row only, nothing shrinkable, so the transcript keeps
            every spare pixel. */}
        <div className="mb-1 flex items-center gap-1 flex-wrap shrink-0">
          <h1
            className="m-0 whitespace-nowrap text-base font-bold bg-gradient-to-r from-[#7d029c] via-[#3b528b] to-[#21908c] bg-clip-text text-transparent"
            title="The agent that learns with you."
          >
            Berg Agents Chat
          </h1>
          {sessionTitle && (
            <span
              className="truncate text-xs text-muted-foreground max-w-64"
              title={`Session: ${sessionTitle}${sessionId ? ` (${sessionId.slice(0, 8)})` : ""}`}
            >
              {sessionTitle}
            </span>
          )}
          {/* Status lives inline in the title row so the transcript
              keeps the pixels (was its own row before). */}
          <span className="flex items-center gap-1" title={statusInfo.label}>
            <span
              className={`w-2 h-2 rounded-full ${statusInfo.pulse ? "animate-pulse" : ""}`}
              style={{ background: statusInfo.color }}
            />
            <span className="text-xs text-muted-foreground">
              {statusInfo.label}
            </span>
          </span>
          <ContextGauge
            sessionId={aiChat.sessionId ?? null}
            streaming={aiChat.isStreaming ?? false}
          />
          <Button
            aria-label="Open sessions (server-side history)"
            size="sm"
            variant="secondary"
            onPress={() => router.push("/history")}
          >
            🕘 Sessions
          </Button>
          <Button
            aria-label="Start a new chat (current chat is saved as a session)"
            size="sm"
            variant="secondary"
            onPress={startNewChat}
          >
            ＋ New chat
          </Button>
          <Button
            aria-label="Jump to the top of the conversation"
            size="sm"
            variant="secondary"
            onPress={() => scrollChatTo("top")}
          >
            ↑ Top
          </Button>
          <Button
            aria-label="Jump to the bottom of the conversation"
            size="sm"
            variant="secondary"
            onPress={() => scrollChatTo("bottom")}
          >
            ↓ Bottom
          </Button>
          {/*
            One button per plugin that declared + shipped a surface.
            Labels and widths come from the plugin's own manifest, so
            a new plugin appears here without touching this file.
          */}
          {pluginSurfaces.map((surface) => {
            const decl = surface.ui as { label?: unknown } | null;
            const label =
              typeof decl?.label === "string" ? decl.label : "Plugin";
            const isOpen = sidePluginId === surface.pluginId;
            return (
              <Button
                key={surface.pluginId}
                aria-label={isOpen ? `Hide ${label}` : `Show ${label}`}
                size="sm"
                variant="secondary"
                onPress={() => {
                  setSidePluginId((prev) =>
                    prev === surface.pluginId ? null : surface.pluginId,
                  );
                  if (!isOpen) {
                    setPluginView("panel");
                  }
                }}
              >
                {label}
                {isOpen && pluginCount > 0 ? ` (${pluginCount})` : ""}
              </Button>
            );
          })}
          <Button
            aria-label={showCatalog ? "Hide plugins" : "Show plugins"}
            size="sm"
            variant="secondary"
            onPress={() => {
              setShowCatalog((prev) => !prev);
              // The catalog owns the right-hand side on its own.
              setSidePluginId(null);
            }}
          >
            🔌 Plugins
          </Button>
          <span className="flex-1" />
          <ThemeToggle />
          <Button
            aria-label="Auto-approve edits in this session"
            size="sm"
            variant={autoApproveEdits ? "primary" : "secondary"}
            onPress={toggleAutoApproveEdits}
          >
            {autoApproveEdits ? "⚡ Auto-approve ON" : "⚡ Auto-approve OFF"}
          </Button>
          <AgentSelector />
          <ProviderSelector />
          <span title="Download this conversation as a Markdown file">
            <Button
              aria-label="Export conversation as markdown"
              className="border border-primary text-primary hover:bg-primary/10"
              size="sm"
              onPress={() => {
                // Large transcripts are multi-megabyte blobs: the
                // object URL must outlive the click, so revocation is
                // deferred (immediate revoke aborts big downloads).
                // Any failure surfaces as a toast, never silence.
                try {
                  const md = buildExportMarkdown(messages, [], null, null);
                  const blob = new Blob([md], { type: "text/markdown" });
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `berg-agents-export-${new Date().toISOString().slice(0, 10)}.md`;
                  document.body.appendChild(link);
                  link.click();
                  link.remove();
                  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
                  const sizeKb = Math.max(1, Math.round(blob.size / 1024));
                  toast.success("Transcript exported", {
                    description: `Saved ~${sizeKb} KB markdown to your downloads.`,
                    timeout: 5000});
                } catch (e) {
                  const toastId = toast.danger("Export failed", {
                    description: String(e),
                    timeout: 0,
                    actionProps: {
                      children: "Dismiss",
                      onPress: () => toast.close(toastId)}});
                }
              }}
            >
              ⬇ Export
            </Button>
          </span>
        </div>

        {/* Activity details - one inline toggle line (no card chrome),
            so it costs almost no vertical space when collapsed. */}
        <div className="mb-1 shrink-0">
          <button
            aria-label={showDetails ? "Hide details" : "Show details"}
            className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            type="button"
            onClick={() => setShowDetails((prev) => !prev)}
          >
            {showDetails ? "▾" : "▸"} Details & Activity
          </button>
          {showDetails && (
            <div className="mt-1">
              <AgentPanel compact activeAgent={null} agents={agents} />
              <RouterStatsPanel compact stats={routerStats} />

              {chatError && (
                <div className="text-red-500 mt-4">
                  Error: {String(chatError)}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Slash command palette - only while the input starts with "/" */}
        {input.startsWith("/") && (
          <SlashCommandAutocomplete
            commands={localCommands}
            onSelect={(cmd) => {
              // Replace the input with the chosen command plus a space.
              setInput(`${cmd.name} `);
            }}
          />
        )}

        {/* HITL approval requests - the agent paused and needs a user
            decision per action: approve one, reject another, edit the
            next. The batch stays on screen (pending + decided items
            with undo) until every item is answered, then the backend
            resumes automatically. Approve-all / reject-all remain as
            batch conveniences. */}
        {approvalBatch.length > 0 && (
          <Card className="mb-1.5 shrink-0 border-warning" variant="default">
            <Card.Header>
              <Card.Title>⏸️ Approval needed</Card.Title>
              <Card.Description>
                The agent wants to run {approvalBatch.length} action
                {approvalBatch.length > 1 ? "s" : ""}. Nothing executes until
                you decide each one — the run resumes once all are answered.
              </Card.Description>
            </Card.Header>
            <Card.Content className="flex flex-col gap-1.5">
              {approvalBatch.map((approval) => (
                <ApprovalItem
                  key={approval.id}
                  approval={approval}
                  isStreaming={isStreaming}
                  onApprove={(id) => respondToApproval(id, true)}
                  onEdit={editApprovalArgs}
                  onReject={(id) =>
                    respondToApproval(
                      id,
                      false,
                      "Rejected by the user. Do NOT attempt this action " +
                        "again in any form — neither the same call with " +
                        "different arguments nor an equivalent edit. " +
                        "Continue without it or ask what to do instead.",
                    )
                  }
                  onRevert={revertApproval}
                />
              ))}
              <div className="flex gap-2">
                <Button
                  isDisabled={isStreaming}
                  size="sm"
                  variant="primary"
                  onPress={() => void respondToAllApprovals(true)}
                >
                  ✅ Approve & run all
                </Button>
                <Button
                  isDisabled={isStreaming}
                  size="sm"
                  variant="secondary"
                  onPress={() =>
                    void respondToAllApprovals(
                      false,
                      "Rejected by the user. Do NOT attempt these actions " +
                        "again in any form — neither the same calls with " +
                        "different arguments nor equivalent edits. " +
                        "Continue without them or ask what to do instead.",
                    )
                  }
                >
                  ❌ Reject all
                </Button>
              </div>
            </Card.Content>
          </Card>
        )}

        {/* HITL questions - the agent paused to ask the user something.
            Mirrors the approval card: one item per ask_user_question
            call (a call may carry several questions, answered
            together), per-call decline, and a decline-all convenience.
            The questions come from the model, so the card reads as the
            model asking - never like a system gate. */}
        {questionBatch.length > 0 && (
          <Card className="mb-1.5 shrink-0 border-warning" variant="default">
            <Card.Header>
              <Card.Title>❓ The model is asking</Card.Title>
              <Card.Description>
                The agent paused to ask you {questionCount}{" "}
                {questionCount > 1 ? "questions" : "question"}. Answer or
                decline each call — the run continues once all are answered.
              </Card.Description>
            </Card.Header>
            <Card.Content className="flex flex-col gap-1.5">
              {questionBatch.map((question) => (
                <QuestionItem
                  key={question.id}
                  isStreaming={isStreaming}
                  question={question}
                  onAnswer={respondToQuestion}
                />
              ))}
              {questionBatch.some((q) => !q.answered) && (
                <div className="flex gap-2">
                  <Button
                    isDisabled={isStreaming}
                    size="sm"
                    variant="secondary"
                    onPress={declineAllQuestions}
                  >
                    🚫 Decline all
                  </Button>
                </div>
              )}
            </Card.Content>
          </Card>
        )}

        {/* A delegated sub-agent's question. Separate from the ask_user
            card above and deliberately not inside it: that surface
            answers a deferred call on the parent, which has paused; this
            answers a question a CHILD asked while the parent is still
            streaming. The cards sit inline in the transcript's flow
            rather than in a chrome row, because the question belongs to
            the work that is still on screen. */}
        {delegationQuestions.map((question) => (
          <DelegationQuestionCard
            key={question.taskId}
            question={question}
            onAnswer={answerDelegation}
          />
        ))}

        {/* Orchestrator HITL gate surfaced in the UI (Phase 1 of
            unifying the two approval systems). When run_task returns
            needs_human_review with planned actions, show them here and
            let the user approve/reject/edit; the decision re-invokes
            run_task with hitl_decision. */}

        {/* The failure dialog - the ONE failure surface. A failed send,
            a failed run (the server's outcome, hint attached), or the
            system's recovery of one. Modal and dismiss-when-read; the
            journal text in the transcript is the durable record. Cleared
            on the next send. */}
        <FailureDialog
          failure={failureNotice}
          onDismiss={dismissFailureNotice}
          onRetry={retryLast}
        />

        {/* Slash-command answer cards - newest last, dismissible. */}
        {cmdCards.length > 0 && (
          <div className="mb-1.5 flex shrink-0 flex-col gap-1.5">
            {cmdCards.map((card) => (
              <Card key={card.id} variant="secondary">
                <Card.Content className="flex items-start gap-2 p-2">
                  <pre className="m-0 flex-1 font-mono text-xs whitespace-pre-wrap">
                    {card.text}
                  </pre>
                  <Button
                    aria-label="Dismiss answer"
                    size="sm"
                    variant="secondary"
                    onPress={() => dismissCmdCard(card.id)}
                  >
                    ✕
                  </Button>
                </Card.Content>
              </Card>
            ))}
          </div>
        )}

        {/* Chat transcript + plugin surface side by side when open:
            the plugin's own component (narrow side-panel by default,
            wide canvas on toggle) or the host's plugin catalog. The
            transcript keeps its own flex column so heights match. */}
        {sidePluginId !== null || showCatalog ? (
          <div className="mb-2 flex min-h-0 flex-1 gap-0">
            <div className="flex min-w-0 flex-1 flex-col">
              <ChatTranscript
                hitlRequest={undefined}
                isExecuting={isStreaming}
                toolResults={toolResults}
                transcript={messages}
                onResolveDelegatedApproval={resolveDelegatedApproval}
              />
            </div>
            {/*
              Drag divider. role=separator + keyboard support so it is
              reachable without a mouse; aria-valuenow reports the width.
            */}
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
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft")
                  setSideWidth((w) =>
                    Math.min(Math.max(320, window.innerWidth - 420), w + 24),
                  );
                if (e.key === "ArrowRight")
                  setSideWidth((w) => Math.max(280, w - 24));
              }}
              onPointerDown={startSideDrag}
            />
            {sidePluginId && activeSurface ? (
              <PluginUISurface
                key={sidePluginId}
                className={pluginView === "canvas" ? "flex-1" : "shrink-0"}
                pluginId={sidePluginId}
                refreshKey={pluginRefreshKey}
                style={
                  pluginView === "canvas" ? undefined : { width: sideWidth }
                }
                ui={activeSurface.ui}
                view={pluginView}
                onClose={() => setSidePluginId(null)}
                onCount={setPluginCount}
                onToggleView={() =>
                  setPluginView((v) => (v === "panel" ? "canvas" : "panel"))
                }
              />
            ) : (
              <PluginCatalog
                className="shrink-0"
                style={{ width: sideWidth }}
                onClose={() => setShowCatalog(false)}
              />
            )}
          </div>
        ) : (
          <ChatTranscript
            hitlRequest={undefined}
            isExecuting={isStreaming}
            toolResults={toolResults}
            transcript={messages}
            onResolveDelegatedApproval={resolveDelegatedApproval}
          />
        )}

        {/* Input bar - always visible at the bottom. shrink-0 so a
            tall transcript can never squeeze it out of view (the
            actual cause of the previous "cropped" input). */}
        <div className="shrink-0 rounded-lg bg-background/95 backdrop-blur">
          {/* Steering strip sits above the input: these are the messages
              the agent has not read yet. They move into the transcript the
              moment the model receives them - never shown in both places. */}
          <SteeringStrip messages={pendingSteering} />
          <InputBar
            input={input}
            placeholder="Type a message... (e.g. 'hello' or 'write a Python script')"
            setInput={setInput}
            streaming={isStreaming}
            onKeyDown={onKeyDown}
            onSend={handleSendWrapper}
            onStop={isStreaming ? stop : undefined}
          />
        </div>
      </div>
    </LazyComponentErrorBoundary>
  );
}

const ChatContentMemo = React.memo(ChatContent);

export default function App() {
  // No provider needed - useChat is hook-based with DefaultChatTransport.
  return <ChatContentMemo />;
}
