/*
 * App component — uses AI SDK v7's useChat hook directly via useAISDKChat.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. The frontend uses useChat from
 * @ai-sdk/react to consume it. No custom EventEmitter, no MockHarness,
 * no RealHarness wrapper — pure AI SDK v7.
 */

import React, { useCallback, useEffect, useState } from "react";

import { Button, Card } from "@heroui/react";

import { useAISDKChat } from "@/harness";
import type { AgentInfo } from "@/harness/webhook";
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

/**
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
        <Card variant="default" className="m-4 border-danger">
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

/**
 * Main chat UI — receives state from useAISDKChat and renders the interface.
 */
function ChatContent() {
  const aiChat = useAISDKChat();
  const {
    messages,
    input,
    setInput,
    handleInputChange,
    isStreaming,
    error: chatError,
    sendMessage,
    stop,
    clearMessages} = aiChat;

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

  // Process slash commands — local commands stay in the UI; /task delegates to the LLM
  const processSlashCommand = useCallback(
    async (text: string) => {
      if (!text.startsWith("/")) return { handled: false };

      const parts = text.trim().split(/\s+/);
      const cmd = parts[0].toLowerCase();

      const localCommands = [
        "help",
        "exit",
        "quit",
        "clear",
        "agents",
        "stats",
        "health",
        "models",
        "tools",
        "history",
        "memory",
        "context",
        "settings",
        "skills",
        "mcps",
        "export"];

      if (localCommands.includes(cmd)) {
        switch (cmd) {
          case "help":
            return {
              handled: true,
              card: `Type a message to chat with Berg, the AI agent.\nFor complex tasks, the agent will automatically use tools (read_file, write_file, edit_file, run_task).\nUse /task <description> to explicitly trigger the full harness pipeline.`};
          case "clear":
            clearMessages();
            return { handled: true, card: null };
          case "exit":
          case "quit":
            return { handled: true, card: null };
          case "agents":
            return {
              handled: true,
              card: `/agents\n\n${agents.map((a) => `${a.name} — ${a.description || ""}`).join("\n") || "No agents"}`};
          case "stats":
            return {
              handled: true,
              card: `/stats\n\n${JSON.stringify(learningStats, null, 2)}`};
          case "health":
            return {
              handled: true,
              card: `/health\nOK · ${messages.length} messages`};
          case "models":
            return {
              handled: true,
              card: "/models\nSwitch via the header selector"};
          case "tools":
            return {
              handled: true,
              card: "/tools\nFile tools + run_task. Use naturally in conversation."};
          default:
            return {
              handled: true,
              card: `${cmd}\n(Type your message to send)`};
        }
      }

      // /harness and /task — let the message through to the LLM.
      if (cmd === "harness" || cmd === "task") {
        return { handled: false };
      }

      return { handled: true, card: `${cmd}\nUnknown command. Type /help.` };
    },
    [agents, learningStats, messages, clearMessages],
  );

  // Send handler — intercepts slash commands, otherwise sends via AI SDK.
  const handleSendWrapper = useCallback(() => {
    if (!input.trim()) return;

    // Check for slash commands
    const cmdMatch = input.trim().match(/^\/(\w+)\s*(.*)/);
    if (cmdMatch) {
      void processSlashCommand(input.trim()).then((outcome) => {
        if (outcome.handled) return;
        void sendMessage(input.trim());
      });
      return;
    }

    // For /task and regular messages, send via AI SDK.
    void sendMessage(input.trim());
  }, [input, processSlashCommand, sendMessage]);

  // Keyboard handling
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendWrapper();
      }
    },
    [handleSendWrapper],
  );

  // Status determination
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
            <Button
              aria-label="Export conversation as markdown"
              className="border border-primary text-primary hover:bg-primary/10"
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
              size="sm"
            >
              ⬇ Export
            </Button>
          </div>
        </div>

        <StatusCard
          status={statusInfo}
          isConnected={true}
          connectionError={chatError ? String(chatError) : null}
        />

        <ChatTranscript
          isExecuting={isStreaming}
          hitlRequest={undefined}
          transcript={messages}
        />

        <div className="relative">
          <InputBar
            disabled={isStreaming}
            input={input}
            onSend={handleSendWrapper}
            onStop={isStreaming ? stop : undefined}
            placeholder="Type a message... (e.g. 'hello' or 'write a Python script')"
            setInput={setInput}
            onKeyDown={onKeyDown}
          />
        </div>

        {/* Activity Details */}
        <Card className="mt-4" variant="default">
          <Card.Header>
            <Card.Title>Details & Activity</Card.Title>
          </Card.Header>
          <Card.Content>
            <AgentPanel compact={false} agents={agents} activeAgent={null} />
            <LearningPanel compact={false} stats={learningStats} />

            {chatError && (
              <div className="text-red-500 mt-4">
                Error: {String(chatError)}
              </div>
            )}
          </Card.Content>
        </Card>
      </div>
    </LazyComponentErrorBoundary>
  );
}

const ChatContentMemo = React.memo(ChatContent);

export default function App() {
  // No provider needed — useChat is hook-based with DefaultChatTransport.
  return <ChatContentMemo />;
}
