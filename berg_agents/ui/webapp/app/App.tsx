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

import type { AgentInfo } from "@/harness/webhook";
import { useAISDKChat } from "@/harness";
import type { Command } from "./components/SlashCommandAutocomplete";
import { SlashCommandAutocomplete } from "./components/SlashCommandAutocomplete";
import type { ToolResult } from "./components/ChatTranscript";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Toast, toast } from "@heroui/react";
import { API_BASE } from "@/envConfig";
import { useRouter } from "next/navigation";
import { buildExportMarkdown } from "@/utils/utils";

import InputBar from "./components/InputBar.tsx";
import ContextGauge from "./components/ContextGauge.tsx";
import ApprovalItem from "./components/ApprovalItem";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import AgentSelector from "./components/AgentSelector.tsx";
import RouterStatsPanel from "./components/RouterStatsPanel.tsx";
import ChatTranscript, {
  CHAT_SCROLL_ID} from "./components/ChatTranscript.tsx";
import { PluginUISurface } from "./plugins/PluginUISurface.tsx";
import { PluginCatalog } from "./components/PluginCatalog.tsx";
import Navbar from "./components/Navbar.tsx";

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
    interruptWith,
    approvalBatch,
    respondToApproval,
    respondToAllApprovals,
    editApprovalArgs,
    revertApproval,
    systemNotice,
    dismissSystemNotice,
    sessionId,
    sessionTitle,
    newServerChat} = aiChat;
  // Backend tool catalog (powers the slash palette + execution).
  // Fetched once, before the palette below reads it: workspace file
  // tools, run_task, and the delegated plan/implement entries, each
  // with a one-line description.
  const [backendTools, setBackendTools] = useState<
    Array<{ name: string; description: string; source: string }>
  >([]);
  useEffect(() => {
    fetch(`${API_BASE}/api/tools`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && Array.isArray(data.tools)) setBackendTools(data.tools);
      })
      .catch(() => setBackendTools([]));
  }, []);

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

  // Local agent list (fetched from /api/agents)
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  useEffect(() => {
    fetch(`${API_BASE}/api/agents`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: AgentInfo[]) => setAgents(data || []))
      .catch(() => setAgents([]));
  }, []);

  // Fetch Router stats on mount
  const [routerStats, setRouterStats] = useState<unknown>(null);
  useEffect(() => {
    fetch(`${API_BASE}/api/router-stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setRouterStats(data))
      .catch(() => {});
  }, []);

  // -------------------------------------------------------------------------
  // Tool-result handling (used by ChatTranscript)
  // -------------------------------------------------------------------------
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);

  // Orchestrator HITL gate surfaced in the UI: when run_task returns
  // status "needs_approval" with action_requests/plan_steps, we show a
  // plan-review approval
  // card (reusing ApprovalItem) instead of a plain tool result. Approve/
  // reject/edit re-invoke run_task with hitl_decision. Phase 1 of
  // unifying the two approval systems (chat batch + orchestrator gate).
  const [pendingGate, setPendingGate] = useState<{
    taskArgs: Record<string, unknown>;
    taskId: string;
    plannedActions: Array<{ action: string; args: Record<string, unknown> }>;
    planSteps: Array<{ description: string; taskType: string }>;
  } | null>(null);

  // Session-scoped opt-in: when on, mutating tool calls / gated plans are
  // auto-approved without pausing. Per-tool approval stays the default;
  // this is a convenience for users who want to be lazy. Persisted so it
  // survives reloads within the same browser.
  const [autoApproveEdits, setAutoApproveEdits] = useState<boolean>(() => {
    try {
      return localStorage.getItem("berg_auto_approve_edits") === "1";
    } catch {
      return false;
    }
  });
  const toggleAutoApproveEdits = () => {
    setAutoApproveEdits((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("berg_auto_approve_edits", next ? "1" : "0");
      } catch {
        /* private mode */
      }
      return next;
    });
  };

  // Session-scoped opt-in: when auto-approve is on, approve all pending
  // chat tool calls without showing the card. Per-tool approval stays
  // the default when the toggle is off.
  useEffect(() => {
    if (!autoApproveEdits) return;
    if (!approvalBatch || approvalBatch.length === 0) return;
    const pending = approvalBatch.filter((a) => !a.decided);
    if (pending.length === 0) return;
    void respondToAllApprovals(true);
  }, [autoApproveEdits, approvalBatch, respondToAllApprovals]);

  // Slash-command result cards: processSlashCommand answers locally
  // (help, agents, stats, /memory, tool runs, ...) and the answer
  // lands here as a dismissible card above the transcript instead
  // of vanishing into the promise chain.
  const [cmdCards, setCmdCards] = useState<Array<{ id: number; text: string }>>(
    [],
  );

  // -------------------------------------------------------------------------
  // Sessions + conversation navigation
  // -------------------------------------------------------------------------
  /** Show/hide the inline Details & Activity panel. */
  const [showDetails, setShowDetails] = useState(false);

  // -------------------------------------------------------------------------
  // Plugin surfaces (side-panel + canvas views), driven entirely by
  // what the plugins declare in their manifests. The host holds no
  // knowledge of any plugin's domain: it learns "this plugin has a
  // surface, here is how to mount it" from GET /api/plugins.
  // -------------------------------------------------------------------------
  /** Plugin id whose surface is open, or the catalog. */
  const [sidePluginId, setSidePluginId] = useState<string | null>(null);
  /** Show the host's plugin catalog (enable/disable, no plugin UI). */
  const [showCatalog, setShowCatalog] = useState(false);
  /** Panel (narrow) vs canvas (wide) presentation. */
  const [pluginView, setPluginView] = useState<"panel" | "canvas">("panel");
  /**
   * Width (px) of the docked side surface. Draggable via the handle
   * between the transcript and the surface — the fixed 340px clipped
   * the MCP/skill descriptions so toggles were unreadable.
   */
  const [sideWidth, setSideWidth] = useState(340);
  /** True while the divider is being dragged (drives the cursor). */
  const [sideDragging, setSideDragging] = useState(false);
  /** Bump to force the open surface to refetch after agent calls. */
  const [pluginRefreshKey, setPluginRefreshKey] = useState(0);
  /** Headline count reported by the open surface (badge). */
  const [pluginCount, setPluginCount] = useState(0);
  /** Registry entries for plugins that shipped a surface. */
  const [pluginSurfaces, setPluginSurfaces] = useState<
    Array<{
      pluginId: string;
      ui: Record<string, unknown> | null;
      tools: string[];
    }>
  >([]);

  // Discover which plugins have a registered surface.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/plugins`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (cancelled || !Array.isArray(data.plugins)) return;
        const found: Array<{
          pluginId: string;
          ui: Record<string, unknown> | null;
          tools: string[];
        }> = [];
        for (const p of data.plugins) {
          if (!p || typeof p.id !== "string" || !p.ui) continue;
          // NOTE: the manifest is the only filter M-bM-^@M-^T any plugin that —
          // declares a `ui:` block is offered. Whether its bundle loads
          // is the bridge's problem, reported on the surface itself.
          found.push({ pluginId: p.id, ui: p.ui, tools: p.tools ?? [] });
        }
        setPluginSurfaces(found);
      } catch {
        // Backend unreachable - no plugin surfaces offered.
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const activeSurface = pluginSurfaces.find((s) => s.pluginId === sidePluginId);
  const activeDecl = activeSurface?.ui as
    { label?: unknown; placement?: unknown } | null | undefined;
  const activeLabel =
    typeof activeDecl?.label === "string" ? activeDecl.label : "Plugin";
  // NOTE: `width` used to come from the manifest; the docked surface is
  // now user-resizable (sideWidth), so the manifest value is ignored.

  // Completed tool calls anywhere in the transcript refresh the open
  // surface, so agent edits appear without manual reloads.
  const activeTools =
    pluginSurfaces.find((s) => s.pluginId === sidePluginId)?.tools ?? [];
  const pluginActivity = messages.reduce(
    (n, m) =>
      n +
      (m.toolCalls?.filter((c) => activeTools.includes(c.tool)).length ?? 0),
    0,
  );
  const seenPluginActivity = useRef(0);
  useEffect(() => {
    if (pluginActivity > seenPluginActivity.current) {
      seenPluginActivity.current = pluginActivity;
      setPluginRefreshKey((k) => k + 1);
    }
  }, [pluginActivity]);

  // -------------------------------------------------------------------------
  // Side-surface resize: pointer-capture divider between the transcript
  // and the docked surface. Width is clamped so the transcript always
  // keeps a usable column, and reset when the surface closes.
  // -------------------------------------------------------------------------
  const sideDragStart = useRef<{ x: number; w: number } | null>(null);

  const onSideDragMove = useCallback((e: PointerEvent) => {
    const start = sideDragStart.current;
    if (!start) return;
    // Dragging left grows the surface (it sits to the right of the
    // divider), so the delta is inverted.
    const next = start.w - (e.clientX - start.x);
    const max = Math.max(320, window.innerWidth - 420);
    setSideWidth(Math.min(max, Math.max(280, next)));
  }, []);

  const onSideDragEnd = useCallback(() => {
    sideDragStart.current = null;
    setSideDragging(false);
  }, []);

  useEffect(() => {
    if (!sideDragging) return;
    window.addEventListener("pointermove", onSideDragMove);
    window.addEventListener("pointerup", onSideDragEnd);
    return () => {
      window.removeEventListener("pointermove", onSideDragMove);
      window.removeEventListener("pointerup", onSideDragEnd);
    };
  }, [sideDragging, onSideDragMove, onSideDragEnd]);

  const startSideDrag = (e: React.PointerEvent) => {
    sideDragStart.current = { x: e.clientX, w: sideWidth };
    setSideDragging(true);
  };

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

      // Split into command token and the rest of the line. The
      // leading slash is stripped so "/read_file" matches the
      // backend tool "read_file" (it stayed on before, and every
      // tool command silently fell through to the model).
      const [cmd, ...rest] = text.trim().split(/\s+/);
      const cmdLower = cmd.toLowerCase().replace(/^\//, "");
      const args = rest.join(" ");

      // -----------------------------------------------------------------
      // Backend-backed tool commands - these hit /api/tool/execute.
      // -----------------------------------------------------------------
      const tool = backendTools.find((t) => t.name.toLowerCase() === cmdLower);
      if (tool && tool.source !== "delegate") {
        try {
          // Parse the argument string as JSON.  If parsing fails we fall back
          // to sending the raw string as a single-property argument.
          let parsedArgs: any;
          try {
            parsedArgs = JSON.parse(args);
          } catch {
            parsedArgs = args;
          }
          await executeTool(tool.name, parsedArgs);
          return { handled: true, card: `✅ ${tool.name} executed` };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ ${tool.name} failed` };
        }
      }
      if (tool && tool.source === "delegate") {
        // plan_task / implement_task only run inside a chat turn, so
        // route them through the harness pipeline instead of direct
        // execution: /plan becomes a planning task, /implement runs
        // the full pipeline on the description.
        const taskArgs = {
          description: args || tool.name,
          task_type: tool.name === "plan_task" ? "plan" : "generic"};
        try {
          const resp = await fetch(`${API_BASE}/api/tool/execute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tool: "run_task", args: taskArgs })});
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const data = await resp.json();
          let parsed: any = data?.output;
          if (typeof parsed === "string") {
            try {
              parsed = JSON.parse(parsed);
            } catch {
              /* keep raw string */
            }
          }
          // Orchestrator plan review: a mutating task returns a plan
          // (concrete action_requests + abstract plan_steps) instead of
          // executing. Surface it as a plan-approval card; the user
          // approves/rejects/edits, then we re-invoke run_task.
          if (
            parsed &&
            parsed.status === "needs_approval" &&
            (Array.isArray(parsed.action_requests) ||
              Array.isArray(parsed.plan_steps))
          ) {
            // Session-scoped opt-in: auto-approve without pausing.
            if (autoApproveEdits) {
              try {
                await fetch(`${API_BASE}/api/tool/execute`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    tool: "run_task",
                    args: {
                      ...taskArgs,
                      task_id: String(parsed.task_id ?? ""),
                      hitl_decision: "approve"}})});
              } catch (e) {
                console.error(e);
              }
              return { handled: true, card: "✅ Auto-approved & ran" };
            }
            setPendingGate({
              taskArgs,
              taskId: String(parsed.task_id ?? ""),
              plannedActions: (Array.isArray(parsed.action_requests)
                ? parsed.action_requests
                : []
              ).map((a: any) => ({
                action: String(a?.action ?? a?.tool ?? "action"),
                args:
                  typeof a?.args === "object" && a?.args !== null ? a.args : {}})),
              planSteps: (Array.isArray(parsed.plan_steps)
                ? parsed.plan_steps
                : []
              ).map((s: any) => ({
                description: String(s?.description ?? ""),
                taskType: String(s?.task_type ?? "")}))});
            return {
              handled: true,
              card: "⏸️ Plan review — see card below"};
          }
          return { handled: true, card: `✅ ${tool.name} via run_task` };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ ${tool.name} failed` };
        }
      }

      // -----------------------------------------------------------------
      // Context catalog - memory files, skills, MCP servers via
      // /api/context (mirrors the TUI /memory /skills /mcps).
      // -----------------------------------------------------------------
      if (
        cmdLower === "memory" ||
        cmdLower === "skills" ||
        cmdLower === "mcps"
      ) {
        try {
          const res = await fetch(`${API_BASE}/api/context`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const ctx = await res.json();
          let card = "";
          if (cmdLower === "memory") {
            const mem = ctx.memory || [];
            card =
              "/memory\n\n" +
              (mem.length > 0
                ? mem
                    .map((m: any) => `${m.exists ? "✅" : "❌"} ${m.path}`)
                    .join("\n")
                : "No memory files configured.");
          } else if (cmdLower === "skills") {
            const sk = ctx.skills || [];
            card =
              "/skills\n\n" +
              (sk.length > 0
                ? sk
                    .map((s: any) => `${s.name} - ${s.description || ""}`)
                    .join("\n")
                : "No skills found.");
          } else {
            const servers = ctx.mcp_servers || [];
            card =
              "/mcps\n\n" +
              (servers.length > 0
                ? servers
                    .map((s: any) => `${s.enabled ? "✅" : "⛔"} ${s.name}`)
                    .join("\n")
                : "No MCP servers configured.");
          }
          return { handled: true, card };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ /${cmdLower} failed` };
        }
      }

      // -----------------------------------------------------------------
      // /compact [optional focus] — shrink this session's history.
      // The client owns the transcript (every turn re-sends it), so
      // compaction has to end in a reload or the next turn undoes it.
      // -----------------------------------------------------------------
      if (cmdLower === "compact") {
        const session = aiChat.sessionId;
        if (!session) {
          return { handled: true, card: "No session to compact yet." };
        }
        try {
          const res = await fetch(
            `${API_BASE}/api/sessions/${encodeURIComponent(session)}/compact`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ focus: args || null })},
          );
          if (!res.ok) {
            const err = await res.text();
            return { handled: true, card: `❌ /compact failed: ${err}` };
          }
          const data = await res.json();
          // Reload from the server so the client's copy matches
          // what was just stored. Without this the next turn
          // re-sends the full history and undoes the compaction.
          await aiChat.openSession(session);
          const saved =
            data.tokens_before && data.tokens_after
              ? `\n~${Math.round(data.tokens_before / 1000)}k → ~${Math.round(data.tokens_after / 1000)}k tokens`
              : "";
          return {
            handled: true,
            card: `/compact\n${data.before} → ${data.after} messages${saved}`};
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ /compact failed: ${e}` };
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
          card: `/stats\n\n${JSON.stringify(routerStats, null, 2)}`};
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
      // Anything else: a slash-prefixed token that is not a recognised
      // command. Do NOT forward it to the model - that produced the
      // confused "Thinking..." + wasted tool calls (e.g. /agent). Surface
      // a clear "unknown command" instead and keep the turn cheap.
      // -----------------------------------------------------------------
      return {
        handled: true,
        card: `Unknown command: ${cmd}\nType /help for the available commands.`};
    },
    [agents, backendTools, clearMessages, input, routerStats, messages],
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
          return;
        }
        // Handled: clear the box and surface the answer card (if any)
        // above the transcript. Without this the card is dropped and
        // every slash command looks like a no-op.
        setInput("");
        if (outcome.card) {
          const text = outcome.card;
          setCmdCards((prev) => [...prev, { id: Date.now(), text }]);
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
            size="sm"
            variant={autoApproveEdits ? "primary" : "secondary"}
            onPress={toggleAutoApproveEdits}
            aria-label="Auto-approve edits in this session"
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
            onClick={() => setShowDetails((prev) => !prev)}
            type="button"
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

        {/* Orchestrator HITL gate surfaced in the UI (Phase 1 of
            unifying the two approval systems). When run_task returns
            needs_human_review with planned actions, show them here and
            let the user approve/reject/edit; the decision re-invokes
            run_task with hitl_decision. */}
        {pendingGate && (
          <Card
            className="mb-1.5 shrink-0 border-warning bg-surface-soft"
            variant="default"
          >
            <Card.Header>
              <Card.Title>📋 Plan review (run_task)</Card.Title>
              <Card.Description>
                The orchestrator planned {pendingGate.plannedActions.length}{" "}
                concrete action
                {pendingGate.plannedActions.length === 1 ? "" : "s"}
                {pendingGate.planSteps.length > 0
                  ? ` across ${pendingGate.planSteps.length} step${pendingGate.planSteps.length === 1 ? "" : "s"}`
                  : ""}
                . Review the whole plan before anything runs.
              </Card.Description>
            </Card.Header>
            <Card.Content className="flex flex-col gap-2">
              {pendingGate.plannedActions.map((a, i) => (
                <div
                  key={i}
                  className="flex flex-col gap-1 rounded-md border border-border bg-surface p-2"
                >
                  <div className="font-mono text-sm font-semibold">
                    {i + 1}. {a.action}
                  </div>
                  {a.args && Object.keys(a.args).length > 0 && (
                    <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
                      {JSON.stringify(a.args, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
              {pendingGate.planSteps.length > 0 && (
                <div className="flex flex-col gap-1">
                  <div className="text-xs text-muted-foreground">
                    Planned steps (guidance):
                  </div>
                  <ol className="text-xs list-decimal ml-4 flex flex-col gap-0.5">
                    {pendingGate.planSteps.map((s, i) => (
                      <li key={i}>
                        {s.taskType ? `${s.taskType}: ` : ""}
                        {s.description}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              <div className="flex gap-2 flex-wrap pt-1">
                <Button
                  size="sm"
                  variant="primary"
                  onPress={async () => {
                    try {
                      await fetch(`${API_BASE}/api/tool/execute`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          tool: "run_task",
                          args: {
                            ...pendingGate.taskArgs,
                            task_id: pendingGate.taskId,
                            hitl_decision: "approve"}})});
                    } finally {
                      setPendingGate(null);
                    }
                  }}
                >
                  ✅ Approve & run
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onPress={async () => {
                    const edited = window.prompt(
                      "Edit planned action args (JSON):",
                      JSON.stringify(pendingGate.plannedActions, null, 2),
                    );
                    if (edited === null) return;
                    let parsed: unknown = edited;
                    try {
                      parsed = JSON.parse(edited);
                    } catch {
                      /* keep raw text */
                    }
                    try {
                      await fetch(`${API_BASE}/api/tool/execute`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          tool: "run_task",
                          args: {
                            ...pendingGate.taskArgs,
                            task_id: pendingGate.taskId,
                            hitl_decision: "edit",
                            edited_action: parsed}})});
                    } finally {
                      setPendingGate(null);
                    }
                  }}
                >
                  ✏️ Edit & run
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onPress={() => {
                    // Reject: do not re-run.
                    setPendingGate(null);
                  }}
                >
                  ❌ Reject
                </Button>
              </div>
            </Card.Content>
          </Card>
        )}

        {/* System recovery notice - a failed send auto-rejected its
            orphaned approvals (see the hook). Visible, dismissible,
            and never part of the message list, so it cannot poison
            future sends. Cleared on the next send. */}
        {systemNotice && (
          <Alert className="mb-1.5 shrink-0" status="warning">
            <Alert.Indicator />
            <Alert.Title>⚠️ Tool run recovered</Alert.Title>
            <Alert.Description>{systemNotice}</Alert.Description>
            <Button
              aria-label="Dismiss recovery notice"
              size="sm"
              variant="secondary"
              onPress={dismissSystemNotice}
            >
              Dismiss
            </Button>
          </Alert>
        )}

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
                    onPress={() =>
                      setCmdCards((prev) =>
                        prev.filter((c) => c.id !== card.id),
                      )
                    }
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
              onKeyDown={(e) => {
                if (e.key === "ArrowLeft")
                  setSideWidth((w) =>
                    Math.min(Math.max(320, window.innerWidth - 420), w + 24),
                  );
                if (e.key === "ArrowRight")
                  setSideWidth((w) => Math.max(280, w - 24));
              }}
              onPointerDown={startSideDrag}
              role="separator"
              tabIndex={0}
            />
            {sidePluginId && activeSurface ? (
              <PluginUISurface
                className={pluginView === "canvas" ? "flex-1" : "shrink-0"}
                key={sidePluginId}
                onClose={() => setSidePluginId(null)}
                onCount={setPluginCount}
                onToggleView={() =>
                  setPluginView((v) => (v === "panel" ? "canvas" : "panel"))
                }
                pluginId={sidePluginId}
                refreshKey={pluginRefreshKey}
                style={
                  pluginView === "canvas" ? undefined : { width: sideWidth }
                }
                ui={activeSurface.ui}
                view={pluginView}
              />
            ) : (
              <PluginCatalog
                className="shrink-0"
                onClose={() => setShowCatalog(false)}
                style={{ width: sideWidth }}
              />
            )}
          </div>
        ) : (
          <ChatTranscript
            hitlRequest={undefined}
            isExecuting={isStreaming}
            toolResults={toolResults}
            transcript={messages}
          />
        )}

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
