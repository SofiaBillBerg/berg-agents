/*
 * App component using the new harness interface with AI SDK streaming.
 * Utility functions extracted to utils/utils.ts for maintainability.
 */

import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, Card } from "@heroui/react";

import { HarnessProvider } from "@/harness/harness-provider";
import { useHarnessState, useHitl, useAgents, useAISDKChat, useTaskExecution } from "@/harness";
import type { HarnessEvent, HitlDecisionInput } from "@/harness/webhook";
import { toAssistantAnswer, buildExportMarkdown } from "@/utils/utils";
import InputBar from "./components/InputBar.tsx";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import SubtaskPanel from "./components/SubtaskPanel.tsx";
import LearningPanel from "./components/LearningPanel.tsx";
import ChatTranscript from "./components/ChatTranscript.tsx";
import SlashCommandPicker, { COMMANDS, filterCommands } from "./components/SlashCommandPicker.tsx";
import StatusCard from "./components/StatusCard.tsx";

// Lazy load heavy components with error boundaries
const HitlSurface = lazy(() => import("./components/HitlSurface.tsx"));

/**
 * Error boundary for lazy-loaded components.
 * Shows a helpful message when a component fails to load or render.
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
    console.error(`${this.props.componentName} failed to load:`, error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Card variant="default" className="m-4 border-danger">
          <Card.Header>
            <Card.Title className="text-danger">Failed to load {this.props.componentName}</Card.Title>
          </Card.Header>
          <Card.Content>
            <p className="text-sm">The {this.props.componentName} component encountered an error.</p>
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

function AppContentRaw() {
  const harnessState = useHarnessState();
  const { executeTask, isExecuting, result, error: taskError } = useTaskExecution();
  const { respondToHitl } = useHitl();
  const { agents, isLoading: agentsLoading } = useAgents();
  const aiChat = useAISDKChat(); // Real-time streaming from harness events

  // Transcript state (persisted to localStorage)
  const [transcript, setTranscript] = useState<Array<{ role: string; content: string }>>(() => {
    try {
      const saved = localStorage.getItem("berg-agents-transcript");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {}
    return [];
  });

  useEffect(() => {
    try { localStorage.setItem("berg-agents-transcript", JSON.stringify(transcript)); } catch {}
  }, [transcript]);

  const [input, setInput] = useState("");
  const [showSlashPicker, setShowSlashPicker] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Process slash commands
  const processSlashCommand = useCallback(async (text: string) => {
    if (!text.startsWith("/")) return { handled: false };

    const parts = text.trim().split(/\s+/);
    const cmd = parts[0].toLowerCase();
    const args = parts.slice(1).join(" ");

    const commonCommands = ["/help", "/exit", "/quit", "/clear", "/agents", "/stats",
      "/health", "/models", "/tools", "/history", "/memory", "/context",
      "/settings", "/skills", "/mcps", "/export"];

    if (commonCommands.includes(cmd)) {
      switch (cmd) {
        case "/help":
          return { handled: true, card: `/help\n\n${COMMANDS.map((c) => `${c.name} — ${c.description}`).join("\n")}` };
        case "/clear":
          setInput(""); return { handled: true, card: null };
        case "/exit": case "/quit":
          setInput(""); return { handled: true, card: null };
        case "/agents":
          return { handled: true, card: `/agents\n\n${(agents || []).map((a: any) => `${a.name} [${a.preferred_complexity}] - ${a.description}`).join("\n") || "No agents"}` };
        case "/stats":
          await harnessState.learning.fetchStats();
          return { handled: true, card: `/stats\n\n${JSON.stringify(harnessState.learning.stats, null, 2)}` };
        case "/health":
          return { handled: true, card: `/health\nStatus: OK\nAgents: ${agents?.length || 0}\nTasks: ${(harnessState.learning.stats as any)?.total || 0}` };
        case "/models":
          return { handled: true, card: "/models\nSwitch models via header selector" };
        case "/tools":
          return { handled: true, card: "/tools\nTools shown in TUI; harness picks per task type" };
        case "/history":
          return { handled: true, card: `/history\n${harnessState.events.length} events` };
        case "/memory":
          return { handled: true, card: "/memory\nSession: active\nLong-term: MemPalace integration pending" };
        case "/context":
          return { handled: true, card: `/context\n${harnessState.events.length} events in history` };
        case "/settings":
          return { handled: true, card: `/settings\n${JSON.stringify({ agents, stats: harnessState.learning.stats }, null, 2)}` };
        case "/skills":
          return { handled: true, card: "/skills\nConfigured server-side — see config" };
        case "/mcps":
          return { handled: true, card: "/mcps\nConfigured server-side — see mcp.json" };
        case "/export":
          return { handled: true, card: null };
      }
    }

    if (cmd === "/harness" || cmd === "/task") {
      if (!args) return { handled: true, card: `${cmd}\nUsage: ${cmd} <task description>` };
      await executeTask(args, "generic");
      return { handled: true, card: `${cmd}\nTask started: ${args}` };
    }

    return { handled: true, card: `${cmd}\nUnknown command. Type /help.` };
  }, [harnessState, agents, executeTask]);

  // Send handler
  const handleSend = useCallback(async () => {
    const message = input.trim();
    if (!message) return;

    const outcome = await processSlashCommand(message);
    if (outcome.handled) {
      setInput("");
      if (outcome.card) setShowSlashPicker(false);
      return;
    }

    if (isExecuting) return;

    try {
      // Use AI SDK streaming for real-time response
      await aiChat.sendMessage(message, "generic");
    } catch (err) {
      console.error("Task failed:", err);
    }
  }, [input, isExecuting, executeTask, processSlashCommand]);

  // Handle HITL decision — uses harness HitlDecisionInput type
  const handleHitlDecision = useCallback(async (decision: HitlDecisionInput | HitlDecisionInput[]) => {
    const threadId = (harnessState.hitl as any)?.task_id || (result as any)?.task_id || "";

    // Normalize to array and get first decision
    const decisions = Array.isArray(decision) ? decision : [decision];
    const firstDecision = decisions[0] as { decision: string } | string;
    const decisionStr = typeof firstDecision === 'string'
      ? firstDecision
      : firstDecision?.decision;

    if (decisionStr !== "approve" && decisionStr !== "edit") {
      setTranscript((prev) => [...prev, {
        role: "assistant",
        content: "⛔ Rejected — nothing was written or changed."
      }]);
    }

    const finalResult = await respondToHitl(threadId, decision as any);
    if (finalResult) {
      const answer = toAssistantAnswer(finalResult);
      if (answer.trim() !== "") {
        setTranscript((prev) => [...prev, { role: "assistant", content: answer }]);
      }
    }
  }, [harnessState.hitl, result, respondToHitl]);

  // Keyboard handling
  const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashPicker) {
      if (event.key === "Escape") { setShowSlashPicker(false); return; }
      const matches = filterCommands(input.startsWith("/") ? input.slice(1) : "");
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSlashIndex((i) => Math.max(0, Math.min(i + 1, matches.length - 1)));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSlashIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        const cmd = matches[Math.min(slashIndex, matches.length - 1)];
        if (cmd) { processSlashCommand(cmd.name).catch(console.error); }
        setShowSlashPicker(false);
        return;
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend().catch(console.error);
    }
  }, [showSlashPicker, input, slashIndex, handleSend]);

  // Status determination — includes AI SDK streaming status
  const status = useMemo(() => {
    if (harnessState.hitl) return { label: "Awaiting your approval", color: "#ff9800", pulse: false };
    if (aiChat.isStreaming) return { label: "Thinking...", color: "#1976d2", pulse: true };
    if (isExecuting) return { label: "Working...", color: "#1976d2", pulse: true };
    return { label: "Idle", color: "#9e9e9e", pulse: false };
  }, [harnessState.hitl, aiChat.isStreaming, isExecuting]);

  return (
    <div className="app-container p-4 w-full max-w-[95vw] mx-auto">
      <div className="berg-title-banner mb-4 flex justify-between items-center flex-wrap gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="m-0 whitespace-nowrap text-2xl font-bold">Berg Agents Chat</h1>
          <p className="mt-1 text-sm text-muted-foreground">The agent that learns with you.</p>
        </div>
        <div className="header-actions flex items-center gap-2 flex-wrap">
          <ThemeToggle />
          <ProviderSelector />
          <Button
            aria-label="Export conversation as markdown"
            className="border border-primary text-primary hover:bg-primary/10"
            onPress={() => {
              const md = buildExportMarkdown(transcript, harnessState.events, harnessState.hitl, null);
              const blob = new Blob([md], { type: "text/markdown" });
              const url = URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = `berg-agents-export-${new Date().toISOString().slice(0,10)}.md`;
              link.click();
              URL.revokeObjectURL(url);
            }}
            size="sm"
          >
            ⬇ Export
          </Button>
        </div>
      </div>

      {/* Working Status — HeroUI v3 Card compound component */}
      <StatusCard
        status={status}
        isConnected={harnessState.connection.isConnected}
        connectionError={harnessState.connection.error}
      />

      {/* Chat Transcript — combines local transcript + AI SDK streaming messages */}
      <ChatTranscript
        isExecuting={aiChat.isStreaming || isExecuting}
        hitlRequest={harnessState.hitl || undefined}
        transcript={[
          ...transcript,
          ...aiChat.messages.map((msg) => ({ role: msg.role, content: msg.content })),
        ]}
      />

      {harnessState.hitl && (
        <Suspense fallback={
          <Card variant="default" className="m-4">
            <Card.Content className="flex items-center gap-2 p-3">
              <span className="text-sm">Loading HITL interface...</span>
            </Card.Content>
          </Card>
        }>
          <LazyComponentErrorBoundary componentName="HITL Surface">
            <HitlSurface
              pending={harnessState.hitl as unknown as Record<string, unknown>}
              onDecision={handleHitlDecision}
            />
          </LazyComponentErrorBoundary>
        </Suspense>
      )}

      <div className="relative">
        <SlashCommandPicker
          filterText={input.startsWith("/") ? input.slice(1) : ""}
          selectedIndex={slashIndex}
          visible={showSlashPicker}
          onSelect={(cmd: string) => { processSlashCommand(cmd).catch(console.error); inputRef.current?.focus(); }}
          onSelectedIndexChange={setSlashIndex}
        />
        <InputBar
          disabled={isExecuting || !!harnessState.hitl}
          input={input}
          onSend={handleSend}
          placeholder="Describe a task... (type / for commands)"
          setInput={(val: React.SetStateAction<string>) => {
            setInput(val);
            if (typeof val === "string") {
              setShowSlashPicker(val === "/" || (val.startsWith("/") && !val.includes(" ")));
              setSlashIndex(0);
            }
          }}
          onKeyDown={onKeyDown}
        />
      </div>

      {/* Activity Details — HeroUI v3 Card compound components */}
      <Card className="mt-4" variant="default">
        <Card.Header>
          <Card.Title>Details & Activity</Card.Title>
        </Card.Header>
        <Card.Content>
          <AgentPanel compact={false} agents={agents || []} activeAgent={null} />
          <SubtaskPanel isPlanning={isExecuting} subtasks={(result as any)?.plan || []} />
          <LearningPanel compact={false} stats={harnessState.learning.stats} />

          {result && (
            <Card className="mt-3" variant="secondary">
              <Card.Header>
                <Card.Title className="text-sm">Full Result JSON</Card.Title>
              </Card.Header>
              <Card.Content>
                <pre className="font-mono text-xs whitespace-pre-wrap break-words">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </Card.Content>
            </Card>
          )}

          {harnessState.events.length > 0 && (
            <Card className="mt-3" variant="secondary">
              <Card.Header>
                <Card.Title className="text-sm">
                  Harness Activity ({harnessState.events.length} events)
                </Card.Title>
              </Card.Header>
              <Card.Content>
                <div className="max-h-64 overflow-y-auto space-y-2">
                  {harnessState.events.map((ev: HarnessEvent, idx: number) => (
                    <div key={idx} className="harness-event font-mono text-xs">
                      <code className="text-blue-600">{ev.type ?? "event"}</code>
                      <pre className="mt-1 overflow-auto">
                        {JSON.stringify(ev.data ?? ev, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              </Card.Content>
            </Card>
          )}
        </Card.Content>
      </Card>

      {taskError && <div className="text-red-500 mt-4">Error: {taskError}</div>}
    </div>
  );
}

const AppContent = React.memo(AppContentRaw);

export default function App() {
  return (
    <HarnessProvider initialMode="mock" initialScenario="success">
      <AppContent />
    </HarnessProvider>
  );
}