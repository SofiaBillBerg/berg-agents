/*
 * App component - uses AI SDK v7's useChat hook directly via useAISDKChat.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. The frontend uses useChat from
 * @ai-sdk/react to consume it. No custom EventEmitter, no MockHarness,
 * no RealHarness wrapper - pure AI SDK v7.
 */

import type { AgentInfo } from "@/harness/webhook";
import type { Command } from "./components/SlashCommandAutocomplete";
import type { ToolResult } from "./components/ChatTranscript";

import React, { useCallback, useEffect, useState } from "react";
import { Button, Card, Disclosure } from "@heroui/react";

import { useAISDKChat } from "@/harness";
import { API_BASE } from "@/envConfig";
import { buildExportMarkdown } from "@/utils/utils";

import InputBar from "./components/InputBar.tsx";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import LearningPanel from "./components/LearningPanel.tsx";
import ChatTranscript from "./components/ChatTranscript.tsx";
import StatusCard from "./components/StatusCard.tsx";
import Navbar from "./components/Navbar.tsx";
import { SlashCommandAutocomplete } from "./components/SlashCommandAutocomplete";
import { ConversationHistory } from "./components/ConversationHistory";

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
    pendingApprovals,
    respondToApproval} = aiChat;

  // Commands for the slash-autocomplete palette
  const localCommands: Command[] = [
    { name: "/help", description: "Show help info" },
    { name: "/agents", description: "List available agents" },
    { name: "/stats", description: "Show stats" },
    { name: "/clear", description: "Clear chat history" },
    { name: "/exit", description: "Exit chat" },
    { name: "/read_file", description: "Read a file via the backend" },
    { name: "/list_files", description: "List a directory via the backend" },
    { name: "/run_task", description: "Run the harness pipeline" }];

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

  const handleSendWrapper = useCallback(() => {
    if (!input.trim()) return;

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

  // -------------------------------------------------------------------------
  // Status determination (error / streaming / idle)
  // -------------------------------------------------------------------------
  const statusInfo = chatError
    ? { label: "Error", color: "#f44336", pulse: false }
    : isStreaming
      ? { label: "Thinking...", color: "#1976d2", pulse: true }
      : { label: "Idle", color: "#9e9e9e", pulse: false };

  return (
    <LazyComponentErrorBoundary componentName="Chat">
      <Navbar />
      <div className="app-container p-4 w-full max-w-[95vw] mx-auto">
        <div className="berg-title-banner mb-4 flex justify-between items-center flex-wrap gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="m-0 whitespace-nowrap text-2xl font-bold">
              Berg Agents Chat
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              The agent that learns with you.
            </p>
          </div>
          <div className="header-actions flex items-center gap-2 flex-wrap">
            <ThemeToggle />
            <ProviderSelector />
            <span title="Download this conversation as a Markdown file">
              <Button
                aria-label="Export conversation as markdown"
                className="border border-primary text-primary hover:bg-primary/10"
                size="sm"
                onPress={() => {
                  const md = buildExportMarkdown(messages, [], null, null);
                  const blob = new Blob([md], { type: "text/markdown" });
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `berg-agents-export-${new Date().toISOString().slice(0, 10)}.md`;
                  link.click();
                  URL.revokeObjectURL(url);
                }}
              >
                ⬇ Export
              </Button>
            </span>
          </div>
        </div>

        {/* Saved chats - collapsed by default so the conversation
            stays front and center. Expands to snapshot/restore. */}
        <Disclosure className="mb-4" defaultExpanded={false}>
          <Disclosure.Heading>
            <Disclosure.Trigger>
              🕘 History
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body>
              <ConversationHistory onSelect={(msgs) => restoreMessages(msgs)} />
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>

        <StatusCard
          connectionError={chatError ? String(chatError) : null}
          isConnected={true}
          status={statusInfo}
        />

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
            yes/no before a mutating tool runs. Answering resumes the
            same run; rejecting tells the model why. */}
        {pendingApprovals.length > 0 && (
          <Card className="mb-4 border-warning" variant="default">
            <Card.Header>
              <Card.Title>⏸️ Approval needed</Card.Title>
              <Card.Description>
                The agent wants to run {pendingApprovals.length} action
                {pendingApprovals.length > 1 ? "s" : ""}. Nothing executes until
                you decide.
              </Card.Description>
            </Card.Header>
            <Card.Content className="flex flex-col gap-3">
              {pendingApprovals.map((approval) => (
                <div
                  key={approval.id}
                  className="flex flex-col gap-2 rounded border border-border p-2"
                >
                  <div className="font-mono text-sm">
                    🔧 {approval.toolName}
                  </div>
                  {approval.args && (
                    <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
                      {approval.args}
                    </pre>
                  )}
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      onPress={() => respondToApproval(approval.id, true)}
                    >
                      ✅ Approve & run
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onPress={() =>
                        respondToApproval(
                          approval.id,
                          false,
                          "Rejected by the user. Do NOT attempt this action " +
                            "again in any form — neither the same call with " +
                            "different arguments nor an equivalent edit. " +
                            "Continue without it or ask what to do instead.",
                        )
                      }
                    >
                      ❌ Reject
                    </Button>
                  </div>
                </div>
              ))}
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

        {/* Input bar at the bottom — sticky so long transcripts can
            never push it out of view. */}
        <div className="relative sticky bottom-2 z-10 bg-background/95 backdrop-blur rounded-lg">
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

        {/* Activity details - compact summaries collapsed by default;
            full views live on the /agents and /stats tabs. */}
        <Disclosure className="mt-4" defaultExpanded={false}>
          <Disclosure.Heading>
            <Disclosure.Trigger>
              Details & Activity
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body>
              <AgentPanel compact activeAgent={null} agents={agents} />
              <LearningPanel compact stats={learningStats} />

              {chatError && (
                <div className="text-red-500 mt-4">
                  Error: {String(chatError)}
                </div>
              )}
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      </div>
    </LazyComponentErrorBoundary>
  );
}

const ChatContentMemo = React.memo(ChatContent);

export default function App() {
  // No provider needed - useChat is hook-based with DefaultChatTransport.
  return <ChatContentMemo />;
}
