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
 * GNU Affero AI General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * Slash commands - the app's local answers, and the cards they land in.
 *
 * A slash command is either answered locally (help, /agents, /stats,
 * /memory, a backend tool run) or handed to the model when the app does
 * not recognise it. The dispatcher is the biggest single function in the
 * app and it belongs to neither the chat hook nor the layout: it is its
 * own concern, so it lives here with the two card lists it fills and the
 * auto-approve opt-in that pairs with tool execution.
 *
 * The bodies are moved verbatim; the only deliberate change is typing
 * `args` as `Record<string, unknown>` instead of `any` (the eslint
 * `no-explicit-any` errors that came with it were pre-existing).
 */

import type { ChatMessage } from "@/harness";
import type { ToolResult } from "../components/ChatTranscript";

import { useCallback, useEffect, useState } from "react";

/** What the hook needs from the chat hook and the app shell. */
export interface UseSlashCommandsDeps {
  /** Base URL of the Berg Agents API. */
  apiBase: string;
  /** The backend tool catalog (the palette + execution). */
  backendTools: Array<{ name: string; description: string; source: string }>;
  /** The agent list. */
  agents: Array<{ name: string; description?: string }>;
  /** Router stats for /stats. */
  routerStats: unknown;
  /** Send a message to the model (the plan/implement commands). */
  sendMessage: (content: string) => Promise<void>;
  /** Clear the live chat (/clear). */
  clearMessages: () => void;
  /** The active session id (the plan/implement commands). */
  sessionId: string | null;
  /** Open a server-side session (/memory restores one). */
  openSession: (id: string) => Promise<void>;
  /** The live transcript (some commands summarise it). */
  messages: readonly ChatMessage[];
  /** The current text in the input box (/read_file reads it). */
  input: string;
  /** The active approval batch, for the auto-approve opt-in. */
  approvalBatch: Array<{ id: string; decided?: boolean; toolName: string }>;
  /** Answer every pending approval (the auto-approve opt-in). */
  respondToAllApprovals: (approved: boolean) => Promise<void>;
}

/** The slash-command surface. */
export interface SlashCommands {
  /** True when mutating calls are auto-approved (persisted opt-in). */
  autoApproveEdits: boolean;
  /** Flip the opt-in (persisted so it survives reloads). */
  toggleAutoApproveEdits: () => void;
  /** Tool-result cards rendered below the transcript. */
  toolResults: ToolResult[];
  /** Dismissible answer cards above the transcript. */
  cmdCards: Array<{ id: number; text: string }>;
  /** Add an answer card (the send handler uses this). */
  addCmdCard: (text: string) => void;
  /** Dismiss one answer card. */
  dismissCmdCard: (id: number) => void;
  /** Run one slash command; returns whether the app handled it. */
  processSlashCommand: (text: string) => Promise<{
    handled: boolean;
    card?: string;
  }>;
  /** Execute a backend tool directly (the tool cards' path). */
  executeTool: (
    tool: string,
    args: Record<string, unknown>,
  ) => Promise<ToolResult>;
}

/**
 * Own the slash-command surface.
 *
 * @param deps - The API base, the catalogs, the chat channels and the
 *     approval batch the opt-in drives.
 * @returns The cards, the opt-in, and the dispatcher.
 */
export function useSlashCommands(deps: UseSlashCommandsDeps): SlashCommands {
  const {
    apiBase,
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
    respondToAllApprovals} = deps;

  // -------------------------------------------------------------------------
  // Tool-result handling (used by ChatTranscript)
  // -------------------------------------------------------------------------
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);

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
  const addCmdCard = useCallback((text: string) => {
    setCmdCards((prev) => [...prev, { id: Date.now(), text }]);
  }, []);
  const dismissCmdCard = useCallback((id: number) => {
    setCmdCards((prev) => prev.filter((c) => c.id !== id));
  }, []);
  const executeTool = async (
    tool: string,
    args: Record<string, unknown>,
  ): Promise<ToolResult> => {
    const resp = await fetch(`${apiBase}/api/tool/execute`, {
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
      // Plan / implement: these run inside a chat turn through the chat
      // agent's own plan_task / implement_task tools, so their mutating
      // steps flow through the SAME approval batch as every other tool
      // call. One approval system, no separate orchestrator gate.
      // -----------------------------------------------------------------
      if (cmdLower === "plan" || cmdLower === "implement") {
        const prompt =
          cmdLower === "plan"
            ? `Plan this task and return a numbered step plan: ${args}`
            : `Implement this task: ${args}`;
        try {
          await sendMessage(prompt);
          return { handled: true, card: "" };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ ${cmdLower} failed` };
        }
      }

      // -----------------------------------------------------------------
      // Backend-backed tool commands - these hit /api/tool/execute.
      // -----------------------------------------------------------------
      const tool = backendTools.find((t) => t.name.toLowerCase() === cmdLower);
      if (tool && tool.source !== "delegate") {
        try {
          // Parse the argument string as JSON.  If parsing fails we fall back
          // to sending the raw string as a single-property argument.
          let parsedArgs: unknown;
          try {
            parsedArgs = JSON.parse(args);
          } catch {
            parsedArgs = args;
          }
          // JSON.parse yields anything; a non-object falls back to the raw
          // string under one key so the tool still receives a mapping.
          const toolArgs: Record<string, unknown> =
            parsedArgs && typeof parsedArgs === "object"
              ? (parsedArgs as Record<string, unknown>)
              : { arg: parsedArgs };
          await executeTool(tool.name, toolArgs);
          return { handled: true, card: `✅ ${tool.name} executed` };
        } catch (e) {
          console.error(e);
          return { handled: true, card: `❌ ${tool.name} failed` };
        }
      }
      if (tool && tool.source === "delegate") {
        // Z3 unification: /plan and /implement run inside a chat turn
        // through the chat agent's own plan_task/implement_task tools,
        // so their mutating steps flow through the SAME approval batch
        // as every other tool call. No second orchestrator gate.
        const prompt =
          tool.name === "plan_task"
            ? `Plan this task and return a numbered step plan: ${args || tool.name}`
            : `Implement this task: ${args || tool.name}`;
        try {
          await sendMessage(prompt);
          return { handled: true, card: "" };
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
          const res = await fetch(`${apiBase}/api/context`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const ctx = await res.json();
          let card = "";
          if (cmdLower === "memory") {
            const mem = ctx.memory || [];
            card =
              "/memory\n\n" +
              (mem.length > 0
                ? mem
                    .map(
                      (m: { exists?: boolean; path?: string }) =>
                        `${m.exists ? "✅" : "❌"} ${m.path ?? ""}`,
                    )
                    .join("\n")
                : "No memory files configured.");
          } else if (cmdLower === "skills") {
            const sk = ctx.skills || [];
            card =
              "/skills\n\n" +
              (sk.length > 0
                ? sk
                    .map(
                      (s: { name?: string; description?: string }) =>
                        `${s.name ?? ""} - ${s.description ?? ""}`,
                    )
                    .join("\n")
                : "No skills found.");
          } else {
            const servers = ctx.mcp_servers || [];
            card =
              "/mcps\n\n" +
              (servers.length > 0
                ? servers
                    .map(
                      (s: { enabled?: boolean; name?: string }) =>
                        `${s.enabled ? "✅" : "⛔"} ${s.name ?? ""}`,
                    )
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
        const session = sessionId;
        if (!session) {
          return { handled: true, card: "No session to compact yet." };
        }
        try {
          const res = await fetch(
            `${apiBase}/api/sessions/${encodeURIComponent(session)}/compact`,
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
          await openSession(session);
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

  return {
    autoApproveEdits,
    toggleAutoApproveEdits,
    toolResults,
    cmdCards,
    addCmdCard,
    dismissCmdCard,
    processSlashCommand,
    executeTool};
}
