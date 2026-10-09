/*
 * App component - uses AI SDK v7's useChat hook directly via useAISDKChat.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. The frontend uses useChat from
 * @ai-sdk/react to consume it. No custom EventEmitter, no MockHarness,
 * no RealHarness wrapper - pure AI SDK v7.
 */

import type { AgentInfo } from "@/harness/webhook";
import type { PendingApproval } from "@/harness";
import type { Command } from "./components/SlashCommandAutocomplete";
import type { ToolResult } from "./components/ChatTranscript";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Toast, toast } from "@heroui/react";

import { useAISDKChat } from "@/harness";
import { API_BASE } from "@/envConfig";
import { buildExportMarkdown } from "@/utils/utils";

import InputBar from "./components/InputBar.tsx";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import LearningPanel from "./components/LearningPanel.tsx";
import ChatTranscript, {
  CHAT_SCROLL_ID} from "./components/ChatTranscript.tsx";
import Navbar from "./components/Navbar.tsx";
import { SlashCommandAutocomplete } from "./components/SlashCommandAutocomplete";
import {
  ConversationHistory,
  snapshotLiveChat} from "./components/ConversationHistory";

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
 * One paused tool call inside the approval batch. Each item gets its
 * own approve / reject / edit controls so the user can approve one,
 * reject another, and edit the next. Decided items stay visible with
 * a badge + undo until the batch resumes.
 */
function ApprovalItem({
  approval,
  isStreaming,
  onApprove,
  onReject,
  onEdit,
  onRevert}: {
  approval: PendingApproval;
  isStreaming: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onEdit: (id: string, args: unknown) => void;
  onRevert: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(approval.args);

  const saveEdit = () => {
    let parsed: unknown = draft;
    try {
      parsed = JSON.parse(draft);
    } catch {
      // Not JSON - pass the raw text through as the edited args.
    }
    onEdit(approval.id, parsed);
    setEditing(false);
  };

  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border p-1.5">
      <div className="font-mono text-sm">
        🔧 {approval.toolName}{" "}
        {approval.decided ? (
          <span className="text-xs">
            {approval.reason ? "❌ Rejected" : "✅ Approved"}
          </span>
        ) : (
          <span className="text-xs">⏳ Pending</span>
        )}
      </div>
      {approval.reason && (
        <div className="text-xs text-muted-foreground">
          Reason: {approval.reason}
        </div>
      )}
      {editing ? (
        <>
          <textarea
            aria-label={`Edit arguments for ${approval.toolName}`}
            className="font-mono bg-surface-soft p-2 rounded text-xs w-full min-h-20"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              isDisabled={isStreaming}
              onPress={saveEdit}
            >
              💾 Save args
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onPress={() => {
                setDraft(approval.args);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </>
      ) : (
        <>
          {approval.args && (
            <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
              {approval.args}
            </pre>
          )}
          {approval.decided ? (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                isDisabled={isStreaming}
                onPress={() => onRevert(approval.id)}
              >
                ↩️ Undo decision
              </Button>
            </div>
          ) : (
            <div className="flex gap-2 flex-wrap">
              <Button
                size="sm"
                variant="primary"
                isDisabled={isStreaming}
                onPress={() => onApprove(approval.id)}
              >
                ✅ Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                isDisabled={isStreaming}
                onPress={() => onReject(approval.id)}
              >
                ❌ Reject
              </Button>
              <Button
                size="sm"
                variant="secondary"
                isDisabled={isStreaming}
                onPress={() => setEditing(true)}
              >
                ✏️ Edit args
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/*
 * Main chat UI - receives state from useAISDKChat and renders the interface.
 */
function ChatContent() {
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
    interruptWith,
    approvalBatch,
    respondToApproval,
    respondToAllApprovals,
    editApprovalArgs,
    revertApproval} = aiChat;

  // Commands for the slash-autocomplete palette
  const localCommands: Command[] = [
    { name: "/help", description: "Show help info" },
    { name: "/agents", description: "List available agents" },
    { name: "/stats", description: "Show stats" },
    { name: "/clear", description: "Clear chat history" },
    { name: "/exit", description: "Exit chat" },
    { name: "/read_file", description: "Read a file via the backend" },
    { name: "/list_files", description: "List a directory via the backend" }];

  // Local agent list (fetched from /api/agents)
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  useEffect(() => {
    fetch(`${API_BASE}/api/agents`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: AgentInfo[]) => setAgents(data || []))
      .catch(() => setAgents([]));
  }, []);

  // Fetch learning stats on mount
  const [learningStats, setLearningStats] = useState<unknown>(null);
  useEffect(() => {
    fetch(`${API_BASE}/api/learning-stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setLearningStats(data))
      .catch(() => {});
  }, []);

  // -------------------------------------------------------------------------
  // Tool-result handling (used by ChatTranscript)
  // -------------------------------------------------------------------------
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);

  // -------------------------------------------------------------------------
  // Sessions + conversation navigation
  // -------------------------------------------------------------------------
  /** Show/hide the saved-sessions panel (resumable chats). */
  const [showHistory, setShowHistory] = useState(false);

  /** Show/hide the inline Details & Activity panel. */
  const [showDetails, setShowDetails] = useState(false);

  /** Scroll the transcript (the page itself never scrolls). */
  const scrollChatTo = (where: "top" | "bottom") => {
    const el = document.getElementById(CHAT_SCROLL_ID);
    if (!el) return;
    el.scrollTo({ top: where === "top" ? 0 : el.scrollHeight });
  };

  /** Park the live chat as a resumable session, then start fresh. */
  const startNewChat = () => {
    stop();
    snapshotLiveChat();
    clearMessages();
    setShowHistory(false);
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
  const executeTool = async (tool: string, args: any): Promise<ToolResult> => {
    const resp = await fetch(`${API_BASE}/api/tool/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, args })});

    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`Tool ${tool} failed: ${err}`);
    }

    // The exact shape of the response depends on your backend implementation.
    // We expect an object like { output: <serialisable result> }.
    const data = await resp.json();

    // Build the result object that ChatTranscript will render.
    const result: ToolResult = {
      tool,
      input: JSON.stringify(args),
      output: data.output,
      expanded: false,
      onToggle: () => {
        // Toggle the expanded state of the just-added result.
        setToolResults((prev) => {
          const newPrev = [...prev];
          const last = newPrev[newPrev.length - 1];
          return [
            ...newPrev.slice(0, newPrev.length - 1),
            { ...last, expanded: !last.expanded }];
        });
      }};
    return result;
  };

  // -------------------------------------------------------------------------
  // Slash-command handling - including backend-backed tool commands
  // -------------------------------------------------------------------------
  const processSlashCommand = useCallback(
    async (text: string) => {
      if (!text.startsWith("/")) return { handled: false };

      // Split into command token and the rest of the line.
      const [cmd, ...rest] = text.trim().split(/\s+/);
      const cmdLower = cmd.toLowerCase();
      const args = rest.join(" ");

      // -----------------------------------------------------------------
      // Backend-backed tool commands - these hit /api/tool/execute.
      // -----------------------------------------------------------------
      const toolCommands = ["read_file", "write_file", "edit_file", "run_task"];
      if (toolCommands.includes(cmdLower)) {
        try {
          // Parse the argument string as JSON.  If parsing fails we fall back
          // to sending the raw string as a single-property argument.
          let parsedArgs: any;
          try {
            parsedArgs = JSON.parse(args);
          } catch {
            parsedArgs = args;
          }
          const result = await executeTool(cmdLower, parsedArgs);
          // The `result` object already has an `onToggle` that updates
          // `toolResults`, so we just return a success flag.
          return { handled: true, card: `✅ ${cmdLower} executed` };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ ${cmdLower} failed` };
        }
      }

      // -----------------------------------------------------------------
      // Local UI commands - these do NOT hit the backend.
      // -----------------------------------------------------------------
      if (cmdLower === "help") {
        return {
          handled: true,
          card: `Type a message to chat with Berg, the AI agent.\nFor complex tasks, the agent will automatically use tools (read_file, write_file, edit_file, run_task).\nUse /task <description> to explicitly trigger the full harness pipeline.`};
      }
      if (cmdLower === "clear") {
        clearMessages();
        return { handled: true, card: null };
      }
      if (cmdLower === "exit" || cmdLower === "quit") {
        return { handled: true, card: null };
      }
      if (cmdLower === "agents") {
        return {
          handled: true,
          card: `/agents\n\n${agents.map((a) => `${a.name} - ${a.description || ""}`).join("\n") || "No agents"}`};
      }
      if (cmdLower === "stats") {
        return {
          handled: true,
          card: `/stats\n\n${JSON.stringify(learningStats, null, 2)}`};
      }
      if (cmdLower === "health") {
        return {
          handled: true,
          card: `/health\nOK . ${messages.length} messages`};
      }
      if (cmdLower === "models") {
        return {
          handled: true,
          card: "/models\nSwitch via the header selector"};
      }
      if (cmdLower === "tools") {
        return {
          handled: true,
          card: "/tools\nFile tools + run_task. Use naturally in conversation."};
      }

      // -----------------------------------------------------------------
      // Anything else - let the message flow to the AI model.
      // -----------------------------------------------------------------
      return { handled: false };
    },
    [agents, clearMessages, input, learningStats, messages],
  );

  // -------------------------------------------------------------------------
  // Send handler - intercepts slash commands, otherwise forwards to AI SDK.
  // While streaming, sending interrupts the in-flight response and
  // redirects with the new message (steering); otherwise it sends.
  // -------------------------------------------------------------------------
  const forwardToModel = useCallback(
    (text: string) => {
      if (isStreaming) {
        void interruptWith(text);
      } else {
        void sendMessage(text);
      }
    },
    [isStreaming, interruptWith, sendMessage],
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
        }
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

  // Surface backend/stream errors as a persistent toast (stays until
  // the user dismisses it) in addition to the inline status record.
  const lastToastedError = useRef<string | null>(null);
  useEffect(() => {
    if (chatError && chatError !== lastToastedError.current) {
      lastToastedError.current = chatError;
      const toastId = toast.danger("Request failed", {
        description:
          chatError.length > 300 ? `${chatError.slice(0, 300)}…` : chatError,
        timeout: 0,
        actionProps: {
          children: "Dismiss",
          onPress: () => {
            lastToastedError.current = null;
            toast.close(toastId);
          }}});
    }
    if (!chatError) {
      lastToastedError.current = null;
    }
  }, [chatError]);

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
          <Button
            aria-label={showHistory ? "Hide sessions" : "Show sessions"}
            size="sm"
            variant="secondary"
            onPress={() => setShowHistory((prev) => !prev)}
          >
            🕘 {showHistory ? "Hide sessions" : "Sessions"}
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
          <span className="flex-1" />
          <ThemeToggle />
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

        {/* Saved sessions - resumable chats. Restoring parks the live
            chat as a session first, so nothing is ever lost. */}
        {showHistory && (
          <div className="mb-2 max-h-48 overflow-y-auto">
            <ConversationHistory onSelect={(msgs) => restoreMessages(msgs)} />
          </div>
        )}

        {/* Activity details - one inline toggle line (no card chrome),
            so it costs almost no vertical space when collapsed. */}
        <div className="mb-1 shrink-0">
          <button
            aria-label={showDetails ? "Hide details" : "Show details"}
            className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            onClick={() => setShowDetails((prev) => !prev)}
            type="button"
          >
            {showDetails ? "▾" : "▸"} Details & Activity
          </button>
          {showDetails && (
            <div className="mt-1">
              <AgentPanel compact activeAgent={null} agents={agents} />
              <LearningPanel compact stats={learningStats} />

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

        {/* HITL approval requests - the agent paused and needs a human
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
                  onEdit={editApprovalArgs}
                  onRevert={revertApproval}
                />
              ))}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  isDisabled={isStreaming}
                  onPress={() => void respondToAllApprovals(true)}
                >
                  ✅ Approve & run all
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  isDisabled={isStreaming}
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

        {/* Chat transcript - now receives any tool results */}
        <ChatTranscript
          hitlRequest={undefined}
          isExecuting={isStreaming}
          toolResults={toolResults}
          transcript={messages}
        />

        {/* Input bar - always visible at the bottom. shrink-0 so a
            tall transcript can never squeeze it out of view (the
            actual cause of the previous "cropped" input). */}
        <div className="shrink-0 rounded-lg bg-background/95 backdrop-blur">
          <InputBar
            input={input}
            placeholder="Type a message... (e.g. 'hello' or 'write a Python script')"
            setInput={setInput}
            onKeyDown={onKeyDown}
            onSend={handleSendWrapper}
            streaming={isStreaming}
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
