import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, CloseButton } from "@heroui/react";

import { useBergHarness } from "./hooks/useBergHarness";
// Data-flow: `useBergHarness` is the single contract-owning source (fetch + SSE + HITL + catalog).
import HitlSurface from "./components/HitlSurface.tsx";
import InputBar from "./components/InputBar.tsx";
import ThemeToggle from "./components/ThemeToggle.tsx";
import ProviderSelector from "./components/ProviderSelector.tsx";
import AgentPanel from "./components/AgentPanel.tsx";
import SubtaskPanel from "./components/SubtaskPanel.tsx";
import ChatTranscript from "./components/ChatTranscript.tsx";
import LearningPanel from "./components/LearningPanel.tsx";
import SlashCommandPicker, {
  COMMANDS,
  filterCommands,
} from "./components/SlashCommandPicker.tsx";

/** One in-app command result card (replaces the old native alert dialogs). */
export interface CommandOutput {
  title: string;
  body: string;
}

/**
 * Collapsible command-result notice. The whole point: information like
 * "where the file was saved" must never be unrecoverable — the user can
 * collapse the body but the title stays, and can always expand it back.
 * Close is available but no longer the only way to reclaim space.
 */
function CmdNotice({
  output,
  onClose,
}: {
  output: CommandOutput;
  onClose: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <Alert status="accent" role="status">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{output.title}</Alert.Title>
        {!collapsed && (
          <Alert.Description>
            <pre className="cmd-output-body whitespace-pre-wrap wrap-break-word">
              {output.body}
            </pre>
          </Alert.Description>
        )}
      </Alert.Content>
      <Button
        aria-label={
          collapsed ? "Expand command output" : "Collapse command output"
        }
        size="sm"
        variant="ghost"
        onPress={() => setCollapsed((c) => !c)}
      >
        {collapsed ? "▸ Expand" : "▾ Collapse"}
      </Button>
      <CloseButton aria-label="Close command output" onPress={onClose} />
    </Alert>
  );
}

/**
 * Extract the displayable assistant answer from a harness result.
 * Primary source is `result.implementation.answer` (harness.py); the
 * fallbacks only cover older/alternate payloads. Greeting fast-path
 * results share this same shape, so no special-casing is needed.
 */
function toAssistantAnswer(result: any): string {
  const impl = result?.implementation;
  if (impl && typeof impl.answer === "string" && impl.answer.trim() !== "") {
    return impl.answer;
  }
  for (const key of ["answer", "response", "output"] as const) {
    const val = result?.[key];
    if (typeof val === "string" && val.trim() !== "") {
      return val;
    }
  }
  return "";
}

/**
 * Build the visible chat transcript for a completed result: the user
 * prompt plus the assistant answer, in `MessageList` item shape.
 */
function toTranscriptHistory(
  result: any,
  prompt: string,
): { role: string; content: string }[] {
  const history: { role: string; content: string }[] = [];
  const userText =
    prompt ||
    (typeof result?.description === "string" ? result.description : "");
  if (userText.trim() !== "") {
    history.push({ role: "user", content: userText });
  }
  const answer = toAssistantAnswer(result);
  if (answer.trim() !== "") {
    history.push({ role: "assistant", content: answer });
  }
  return history;
}

/**
 * Name the export payload parts for an honest confirmation: which of the
 * last result, the N feed events, the pending review, and the on-screen
 * command output actually went into the file.
 */
function describeExportSources(opts: {
  hasResult: boolean;
  eventCount: number;
  hasHitl: boolean;
  hasCmdOutput: boolean;
}): string {
  const parts: string[] = [];
  if (opts.hasResult) parts.push("last result");
  if (opts.eventCount > 0)
    parts.push(`${opts.eventCount} event${opts.eventCount === 1 ? "" : "s"}`);
  if (opts.hasHitl) parts.push("pending human review");
  if (opts.hasCmdOutput) parts.push("command output");
  return parts.length > 0 ? parts.join(", ") : "session export";
}

function AppContentRaw() {
  // Compound component: owns harness data-flow (useBergHarness) + UI sub-components.
  // Single data source: typed Berg hook.
  const harness = useBergHarness();

  const [input, setInput] = useState("");
  const [showSlashPicker, setShowSlashPicker] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  // In-app result card for slash commands (selectable, dismissible).
  const [cmdOutput, setCmdOutput] = useState<CommandOutput | null>(null);
  // Accumulated chat transcript (user + assistant messages), persisted
  // to localStorage so a page reload or dev-server restart never loses
  // the conversation — the chat is the product, not session state.
  const [transcript, setTranscript] = useState<
    Array<{ role: string; content: string }>
  >(() => {
    try {
      const saved = localStorage.getItem("berg-agents-transcript");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      /* corrupted storage -> start empty */
    }
    return [];
  });
  useEffect(() => {
    try {
      localStorage.setItem(
        "berg-agents-transcript",
        JSON.stringify(transcript),
      );
    } catch {
      /* storage full/unavailable -> transcript still works in-session */
    }
  }, [transcript]);
  const inputRef = useRef(null);

  // Run visibility comes from the harness panels
  // below (SubtaskPanel plan steps + the `harness.events` activity feed,
  // seeded by the sync path and appended by the SSE transport).

  /**
   * Build the session export as markdown: conversation transcript,
   * full harness event feed, pending HITL review, and command
   * output. Pure helper so both the header Export button and the
   * /export command share it.
   */
  const buildExportMarkdown = useCallback(() => {
    const lines: string[] = [
      "# Berg Agents session export",
      "",
      `_Exported ${new Date().toLocaleString()}_`,
      "",
      "---",
      "",
    ];

    // 1. Conversation transcript (user + assistant messages).
    if (transcript.length > 0) {
      lines.push("## Conversation", "");
      transcript.forEach((msg) => {
        const header =
          msg.role === "assistant"
            ? "🤖 **Assistant**"
            : msg.role === "user"
              ? "🧑 **You**"
              : msg.role === "system"
                ? "⚙️ **System**"
                : msg.role;
        lines.push(header, "", msg.content || "", "", "---", "");
      });
    } else if (harness.result) {
      lines.push(
        "## Last task result",
        "",
        "**Status:** " + (harness.result.status || "completed"),
        "",
        "**Task ID:** " + (harness.result.task_id || "N/A"),
        "",
        "**Complexity:** " + (harness.result.complexity || "standard"),
        "",
        "```json",
        JSON.stringify(harness.result, null, 2),
        "```",
        "",
      );
    }

    // 2. Full harness event feed (every completed event).
    if (harness.events.length > 0) {
      lines.push("## Events", "");
      harness.events.forEach((event: any, idx: number) => {
        const eventType = event?.type || "unknown";
        const eventData = event?.data ?? event;
        lines.push(
          `### Event ${idx + 1}: ${eventType}`,
          "",
          "```json",
          JSON.stringify(eventData, null, 2),
          "```",
          "",
        );
      });
      lines.push("---", "");
    }

    // 3. Pending human review (HITL request details).
    if (harness.hitlRequest != null) {
      lines.push("## Pending Human Review", "");
      const hitl = harness.hitlRequest as any;
      lines.push(
        "**Status:** Awaiting approval",
        "",
        "**Reasons:**",
        ...(Array.isArray(hitl.review_reasons)
          ? hitl.review_reasons.map((r: string) => `- ${r}`)
          : []),
        "",
        "**Risk Level:** " + (hitl.risk_level || "N/A"),
        "",
        "**Complexity:** " + (hitl.complexity || "N/A"),
        "",
        "---",
        "",
      );
    }

    // 4. Command output (from slash commands).
    if (cmdOutput) {
      lines.push("## Command Output", "");
      lines.push(`### ${cmdOutput.title}`, "", cmdOutput.body, "", "---", "");
    }

    return lines.join("\n");
  }, [
    transcript,
    harness.events,
    harness.hitlRequest,
    harness.result,
    cmdOutput,
  ]);

  /**
   * True when there is anything worth exporting yet. A gated task leaves
   * result null, so a pending human review (and any
   * on-screen command output) must also enable the button.
   */
  const hasExportable =
    harness.result != null ||
    harness.events.length > 0 ||
    harness.hitlRequest != null ||
    cmdOutput != null;

  /**
   * Save the current session as a markdown file. Prefers the File
   * System Access picker so the user chooses the destination;
   * falls back to an anchor download where it is unavailable.
   * Returns the result card to show (confirmation or a
   * nothing-to-export-yet note).
   */
  const runExport = useCallback(async (): Promise<CommandOutput> => {
    if (!hasExportable) {
      return {
        title: "/export",
        body: "Nothing to export yet — run a task first and the result plus activity feed will land in the markdown file.",
      };
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const defaultName = `berg-agents-export-${stamp}.md`;
    const markdown = buildExportMarkdown();
    const source = describeExportSources({
      hasResult: harness.result != null,
      eventCount: harness.events.length,
      hasHitl: harness.hitlRequest != null,
      hasCmdOutput: cmdOutput != null,
    });
    let filename = defaultName;
    try {
      // File System Access API gives us a save-file dialog where supported.

      const picker = (
        window as unknown as {
          showSaveFilePicker?: (o: unknown) => Promise<any>;
        }
      ).showSaveFilePicker;
      const handle = picker
        ? await picker({
            suggestedName: defaultName,
            types: [
              {
                description: "Markdown export",
                accept: { "text/markdown": [".md"] },
              },
            ],
          })
        : null;
      if (
        handle &&
        typeof (handle as { createWritable?: () => Promise<unknown> })
          .createWritable === "function"
      ) {
        const writable = await (
          handle as { createWritable: () => Promise<unknown> }
        ).createWritable();
        await (writable as { write: (data: string) => Promise<void> }).write(
          markdown,
        );
        await (writable as { close: () => Promise<void> }).close();
        filename = (handle as { name?: string }).name ?? defaultName;
        return {
          title: "/export",
          body: `Successfully exported ${filename} (source: ${source}).`,
        };
      }
      // Picker API missing entirely (e.g. Firefox): fall back to a
      // download, and tell the user exactly where it went and how to
      // get a location dialog in their browser settings.
      const blob = new Blob([markdown], {
        type: "text/markdown;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = defaultName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return {
        title: "/export",
        body:
          `Downloaded ${defaultName} (source: ${source}). ` +
          "This browser has no save-location picker, so the file went to " +
          "the browser's download folder (usually ~/Downloads). " +
          "In Chromium-based browsers you get a real save dialog instead.",
      };
    } catch (err) {
      // User cancelled the picker dialog: no export, no download.
      if ((err as DOMException)?.name === "AbortError") {
        return { title: "/export", body: "Export cancelled." };
      }
      console.error("showSaveFilePicker failed:", err);
      const blob = new Blob([markdown], {
        type: "text/markdown;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = defaultName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return {
        title: "/export",
        body:
          `Save dialog failed (${(err as Error)?.name ?? "error"}): ` +
          `${(err as Error)?.message ?? String(err)}. ` +
          `Downloaded ${defaultName} to your browser's download folder instead.`,
      };
    }
  }, [
    buildExportMarkdown,
    hasExportable,
    harness.events.length,
    harness.result,
    harness.hitlRequest,
    cmdOutput,
  ]);

  /**
   * Append the task result as a transcript entry: user's prompt + the
   * assistant's answer from harness.result.implementation.answer.
   */
  const appendTaskResult = useCallback(
    (taskDesc: string, taskResult?: Record<string, unknown> | null) => {
      const result =
        taskResult ?? (harness.result as Record<string, unknown> | null);
      const answer = (result?.implementation as Record<string, unknown> | null)
        ?.answer;
      const newEntries: Array<{ role: string; content: string }> = [];
      if (taskDesc.trim() !== "")
        newEntries.push({ role: "user", content: taskDesc });
      if (typeof answer === "string" && answer.trim() !== "")
        newEntries.push({ role: "assistant", content: answer });
      if (newEntries.length > 0)
        setTranscript((prev) => [...prev, ...newEntries]);
    },
    [harness.result],
  );

  /**
   * Process a slash command from the WebUI.
   * Returns `{handled, card}` — `handled` false means "not a slash command,
   * treat as a task". Every handled command renders an in-app, selectable
   * result card (never a native alert dialog).
   * NOTE: history/context answers are derived from `harness` (SSE events +
   * last result) — the old `stream.messages` transcript no longer exists.
   */
  const processSlashCommand = useCallback(
    async (
      text: string,
    ): Promise<{
      handled: boolean;
      card?: CommandOutput | null;
    }> => {
      if (!text.startsWith("/")) return { handled: false };

      const parts = text.trim().split(/\s+/);
      const cmd = parts[0].toLowerCase();
      const args = parts.slice(1).join(" ");
      const card = (title: string, body: string) => ({
        handled: true,
        card: { title, body } as CommandOutput,
      });

      // Commands that work in both modes
      const commonCommands = [
        "/help",
        "/exit",
        "/quit",
        "/clear",
        "/agents",
        "/stats",
        "/health",
        "/models",
        "/tools",
        "/history",
        "/memory",
        "/context",
        "/settings",
        "/skills",
        "/mcps",
        "/export",
      ];
      if (commonCommands.includes(cmd)) {
        switch (cmd) {
          case "/help":
            return card(
              "/help — available commands",
              COMMANDS.map((c) => `${c.name} — ${c.description}`).join("\n") +
                "\n\nTip: type / to filter commands, Enter runs the highlighted one.",
            );
          case "/clear":
            // No chat transcript exists anymore, so clearing resets the
            // input box and dismisses the output card. `harness.executeTask`
            // already resets result/subtasks on every run, so harness
            // state never bleeds between tasks.
            setInput("");
            setCmdOutput(null);
            return { handled: true, card: null };
          case "/exit":
          case "/quit":
            // In webui, just clear for now
            setInput("");
            setCmdOutput(null);
            return { handled: true, card: null };
          case "/agents": {
            const list = (harness.agents || []).map(
              (a) => `${a.name} [${a.preferred_complexity}] - ${a.description}`,
            );
            return card(
              "/agents",
              list.length > 0
                ? list.join("\n")
                : "No agents registered — the backend returned an empty agent list.",
            );
          }
          case "/stats":
            await harness.fetchLearningStats();
            return card(
              "/stats",
              JSON.stringify(harness.learningStats, null, 2) ??
                "No learning stats reported yet.",
            );
          case "/health":
            return card(
              "/health",
              `Status: OK\nAgents: ${harness.agents?.length || 0}\nTasks with learning outcomes: ${
                ((harness.learningStats as Record<string, unknown> | null)
                  ?.total as number) ?? 0
              }`,
            );
          case "/models":
            return card(
              "/models",
              "Switch models with the Model selector in the header toolbar — it lists every provider/model pair the backend reports via /api/providers.",
            );
          case "/tools":
            return card(
              "/tools",
              "The full tool list lives in the TUI. In the WebUI the harness picks tools per task type — watch the Harness activity feed during a run to see them.",
            );
          case "/history":
            // Harness equivalent of chat history: hook lifecycle events
            // plus a summary of the last completed result.
            return card(
              "/history",
              `${harness.events.length} harness event${harness.events.length === 1 ? "" : "s"}\nLast result: ${harness.result ? JSON.stringify(harness.result).substring(0, 500) : "No task run yet"}`,
            );
          case "/memory":
            return card(
              "/memory",
              "Session memory: active\nLong-term memory: MemPalace integration pending",
            );
          case "/context":
            // Harness equivalent of token context: event/result payload size.
            return card(
              "/context",
              `${harness.events.length} events in history\nPayload chars: ${JSON.stringify(harness.events).length + JSON.stringify(harness.result ?? "").length}`,
            );
          case "/settings": {
            // display config used in runtime - as parsed (not raw file)
            const active_config = {
              agents: harness.agents,
              learningStats: harness.learningStats,
            };
            console.log(active_config);
            return card(
              "/settings",
              `Active runtime config (as parsed):\n${JSON.stringify(active_config, null, 2)}`,
            );
          }
          case "/skills":
            return card(
              "/skills",
              "Skills are configured server-side — see config/bergagents.jsonc for the current list.",
            );
          case "/mcps":
            return card(
              "/mcps",
              "MCP servers are configured server-side — see mcp.json for connection status.",
            );
          case "/export":
            return { handled: true, card: await runExport() };
        }
      }

      // Harness commands
      if (cmd === "/harness" || cmd === "/task") {
        if (!args) {
          return card(
            cmd,
            `Usage: ${cmd} <task description>\nExample: ${cmd} summarize the repo structure`,
          );
        }
        await harness.executeTask(args, "generic");
        return card(cmd, `Task started: ${args}`);
      }

      return card(
        cmd,
        `Unknown command "${cmd}". Type /help to see everything this UI understands.`,
      );
    },
    [harness, runExport],
  );

  /**
   * Execute one slash command string (from the input, the picker, or a
   * click) and show its result card. Harness commands (/harness, /task)
   * run the task and report back in the same card.
   */
  const executeSlash = useCallback(
    async (text: string) => {
      setShowSlashPicker(false);
      const outcome = await processSlashCommand(text);
      if (!outcome.handled) return;
      setInput("");
      setCmdOutput(outcome.card ?? null);
    },
    [processSlashCommand],
  );

  /**
   * Send the current input: slash commands are handled locally, everything
   * else becomes a harness task. Single owner — no duplicate handleHarness.
   */
  const handleSend = useCallback(async () => {
    const message = input.trim();
    if (!message) return;

    const outcome = await processSlashCommand(message);
    if (outcome.handled) {
      setInput("");
      setCmdOutput(outcome.card ?? null);
      return;
    }

    if (harness.isExecuting) {
      console.log("[DEBUG] handleSend aborted: harness is executing");
      return;
    }
    setInput("");
    try {
      // async-parallel: in future, harness.executeTask and fetch stats could run in Promise.all for independent paths; kept sequential for HITL order.
      const data = await harness.executeTask(message, "generic");
      await harness.fetchLearningStats();
      const newEntries = toTranscriptHistory(data ?? harness.result, message);
      setTranscript((prev) => [...prev, ...newEntries]);
    } catch (err: unknown) {
      console.error("[DEBUG] harness error:", err);
      const msg = (err as Error)?.message || String(err);
      setCmdOutput({ title: "Model call failed", body: msg });
    }
  }, [input, harness, processSlashCommand]);

  // HITL decisions go straight to `harness.respondToHitl` in the
  // HitlSurface below (no local wrapper).

  /**
   * Single owner of Enter/ArrowUp/ArrowDown/Escape while the command
   * palette is open: arrows move the highlight, Enter executes the
   * highlighted command, Escape closes the palette. The picker itself
   * renders the list and handles clicks — it never touches keys.
   */
  const onKeyDown = useCallback(
    (event: any) => {
      if (showSlashPicker) {
        if (event?.key === "Escape") {
          setShowSlashPicker(false);
          return;
        }
        const matches = filterCommands(
          input.startsWith("/") ? input.slice(1) : "",
        );
        if (event?.key === "ArrowDown") {
          if (event.preventDefault) event.preventDefault();
          setSlashIndex((i) =>
            Math.max(0, Math.min(i + 1, matches.length - 1)),
          );
          return;
        }
        if (event?.key === "ArrowUp") {
          if (event.preventDefault) event.preventDefault();
          setSlashIndex((i) => Math.max(0, i - 1));
          return;
        }
        if (event?.key === "Enter" && !event?.shiftKey) {
          if (event.preventDefault) event.preventDefault();
          const cmd = matches[Math.min(slashIndex, matches.length - 1)];
          if (cmd) {
            executeSlash(cmd.name).catch((e) =>
              console.error("[DEBUG] slash execute failed:", e),
            );
          } else {
            setShowSlashPicker(false);
          }
          return;
        }
      }
      if (event?.key === "Enter" && !event?.shiftKey) {
        if (event.preventDefault) event.preventDefault();
        handleSend()
          .then((r) => console.log("[DEBUG] handleSend completed:", r))
          .catch((e) => console.error("[DEBUG] handleSend failed:", e));
      }
    },
    [handleSend, showSlashPicker, input, slashIndex, executeSlash],
  );

  // Liveness during a run is shown by SubtaskPanel (plan steps)
  // and the SSE activity feed below.
  const status = harness.hitlRequest
    ? {
        label: "Awaiting your approval",
        color: "#ff9800",
        pulse: false,
      }
    : harness.isResuming
      ? {
          label: "Resuming approved task…",
          color: "#1976d2",
          pulse: true,
        }
      : harness.isExecuting
        ? { label: "Working...", color: "#1976d2", pulse: true }
        : { label: "Idle", color: "#9e9e9e", pulse: false };

  return (
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
          {/* Header keeps view-level controls only; per-run controls
              (mode toggle, new-chat, thread chip) were removed
              with the old streaming view rather than shimmed. */}
          <ThemeToggle />

          {/* Active Provider and Model Selector — single unified dropdown */}
          <ProviderSelector />

          {/* Export the session (last result + activity feed) as markdown */}
          <Button
            aria-label="Export conversation as markdown"
            isDisabled={!hasExportable}
            variant="secondary"
            onPress={() => {
              void runExport().then(setCmdOutput);
            }}
          >
            ⬇ Export
          </Button>
        </div>
      </div>

      {/* Working-status indicator */}
      <div className="working-status">
        <span
          className={`working-dot ${status.pulse ? "pulse" : ""}`}
          style={{ background: status.color }}
        />
        <span style={{ color: status.color }}>{status.label}</span>
      </div>

      <ChatTranscript
        hitlRequest={harness.hitlRequest}
        isExecuting={harness.isExecuting}
        transcript={transcript}
      />

      {harness.hitlRequest && (
        <HitlSurface
          pending={harness.hitlRequest}
          onDecision={(decision) => {
            const threadId =
              ((harness.hitlRequest as unknown as Record<string, unknown>)
                ?.task_id as string) ||
              ((harness.result as Record<string, unknown> | null)
                ?.task_id as string) ||
              "";
            const parts = Array.isArray(decision) ? decision : [decision];
            const d = parts[0];
            const kind = d?.decision ?? "approve";
            // Reject/dismiss: close the loop in the transcript so the
            // conversation never silently ends on a decision.
            if (kind !== "approve" && kind !== "edit") {
              setTranscript((prev) => [
                ...prev,
                {
                  role: "assistant",
                  content:
                    "⛔ You rejected this action — nothing was written or changed.",
                },
              ]);
              harness.respondToHitl(threadId, decision).catch(() => {});
              return;
            }
            const taskDesc =
              ((harness.hitlRequest as unknown as Record<string, unknown>)
                ?.description as string) ?? "";
            harness.respondToHitl(threadId, decision).then((result) => {
              if (result) {
                const answer =
                  (result?.implementation as Record<string, unknown> | null)
                    ?.answer ||
                  (result?.plan as Record<string, unknown> | null)?.answer ||
                  "";
                const answerText =
                  typeof answer === "string" && answer.trim() !== ""
                    ? answer
                    : "Task completed.";
                setTranscript((prev) => {
                  // Avoid duplicating the user turn: handleSend already
                  // logged it when the task was originally sent.
                  const last = prev[prev.length - 1];
                  const entries =
                    last?.role === "user" && last?.content === taskDesc
                      ? []
                      : [{ role: "user", content: taskDesc }];
                  return [
                    ...prev,
                    ...entries,
                    { role: "assistant", content: answerText },
                  ];
                });
                const impl = result?.implementation as Record<
                  string,
                  unknown
                > | null;
                const modelRun = impl?.model_run as Record<
                  string,
                  unknown
                > | null;
                const files = modelRun?.files_changed as
                  Record<string, unknown>[] | undefined;
                if (Array.isArray(files) && files.length > 0) {
                  setCmdOutput({
                    title: "Files changed",
                    body: (files as Array<Record<string, unknown>>)
                      .map(String)
                      .join("\n"),
                  });
                }
              }
            });
          }}
        />
      )}

      {/* Slash command palette - shows when input starts with /. */}
      <div className="relative">
        <SlashCommandPicker
          filterText={input.startsWith("/") ? input.slice(1) : ""}
          selectedIndex={slashIndex}
          visible={showSlashPicker}
          onSelect={(cmd: string) => {
            executeSlash(cmd).catch((e) =>
              console.error("[DEBUG] slash execute failed:", e),
            );
            inputRef.current?.focus();
          }}
          onSelectedIndexChange={setSlashIndex}
        />
        {/* In-app command result card: collapsible HeroUI Alert.
            Collapse hides the body but keeps the title visible, so the
            info (e.g. where a file was saved) is never lost — Close only
            when truly done with it. */}
        {cmdOutput && (
          <CmdNotice output={cmdOutput} onClose={() => setCmdOutput(null)} />
        )}
        <InputBar
          disabled={
            harness.isExecuting || harness.isResuming || !!harness.hitlRequest
          }
          input={input}
          onSend={handleSend}
          // Block new sends while a task runs, resumes after approval,
          // or waits for approval (previously: chat `isLoading || !!interrupt`).
          placeholder="Describe a task... (type / for commands)"
          setInput={(val: React.SetStateAction<string>) => {
            setInput(val);
            // Show picker when input starts with / and is just the slash
            if (typeof val === "string") {
              setShowSlashPicker(
                val === "/" || (val.startsWith("/") && !val.includes(" ")),
              );
              // New filter text → highlight starts at the top.
              setSlashIndex(0);
            }
          }}
          onKeyDown={(e: { key: string }) => {
            if (showSlashPicker && e.key === "Escape") {
              setShowSlashPicker(false);
              return;
            }
            onKeyDown(e);
          }}
        />
      </div>

      {/* No stop button: cancelling needs a thread id the view no longer
          tracks, so there was no equivalent to rewire to — removed
          rather than shimmed. */}
      {/* Harness chrome: post-actions, agent routing, learning
          stats, result JSON, and the activity feed. Secondary to
          the conversation, so it lives in a collapsed section
          below the input instead of crowding the chat. */}
      <details className="harness-chrome">
        <summary>Details &amp; activity</summary>
        {/* Post-action visibility: files_changed, curation, subagents, background tasks */}
        {harness.result &&
          (() => {
            const r = harness.result as Record<string, unknown>;
            const impl = (r?.implementation ?? null) as Record<
              string,
              unknown
            > | null;
            const modelRun = (impl?.model_run ?? null) as Record<
              string,
              unknown
            > | null;
            const filesChanged = modelRun?.files_changed;
            const curation = (r?.curation ?? null) as Record<
              string,
              unknown
            > | null;
            return (
              <div className="post-actions rounded-xl border border-border bg-surface p-3 my-2">
                <div className="text-xs font-semibold tracking-wider text-muted uppercase mb-2">
                  Post-actions
                </div>
                <div className="flex flex-wrap gap-2 text-sm">
                  {Array.isArray(filesChanged) && filesChanged.length > 0 && (
                    <span className="rounded bg-foreground px-1.5 py-0.5 text-xs font-bold text-background">
                      files_changed: {(filesChanged as string[]).join(", ")}
                    </span>
                  )}
                  {curation && (
                    <span className="rounded bg-foreground px-1.5 py-0.5 text-xs font-bold text-background">
                      curation: {(curation.status as string) || "done"}
                    </span>
                  )}
                  {r?.subagents != null && (
                    <span className="rounded bg-foreground px-1.5 py-0.5 text-xs font-bold text-background">
                      subagents: active
                    </span>
                  )}
                  {r?.background_tasks != null && (
                    <span className="rounded bg-foreground px-1.5 py-0.5 text-xs font-bold text-background">
                      background tasks: running
                    </span>
                  )}
                </div>
              </div>
            );
          })()}

        {/* Harness error surface. */}
        {harness.error && (
          <p className="error-text">
            Error:{" "}
            {typeof harness.error === "string"
              ? harness.error
              : JSON.stringify(harness.error)}
          </p>
        )}

        {/* Harness panels: agent routing, subtasks, HITL approvals, and
            learning stats. Shown unconditionally — this view is always the
            harness. */}
        <AgentPanel
          compact
          activeAgent={
            ((harness.result as Record<string, unknown> | null)?.status as
              string | null) ?? null
          }
          agents={harness.agents}
        />
        <SubtaskPanel
          isPlanning={harness.isExecuting}
          subtasks={harness.subtasks}
        />
        <LearningPanel compact stats={harness.learningStats} />

        {harness.result && (
          <details>
            <summary>
              Show full result JSON (status:{" "}
              {String(harness.result?.status ?? "done")})
            </summary>
            <pre className="mt-2 p-2 bg-surface-tint rounded-sm text-xs whitespace-pre-wrap break-words">
              {JSON.stringify(harness.result, null, 2)}
            </pre>
          </details>
        )}

        {/* Harness activity feed: lifecycle events seeded by the sync path plus SSE. */}
        {harness.events.length > 0 && (
          <details className="tool-activity" open={harness.isExecuting}>
            <summary>
              Harness activity ({harness.events.length} event
              {harness.events.length === 1 ? "" : "s"})
              {harness.isExecuting && " running..."}
            </summary>
            <div className="mt-1 max-h-[50vh] overflow-y-auto">
              {harness.events.map((ev: unknown, idx: number) => {
                const e = ev as { type?: string; data?: unknown };
                return (
                  <div key={idx} className="harness-event">
                    <code>{e.type ?? "event"}</code>
                    <pre>{JSON.stringify(e.data ?? e, null, 2)}</pre>
                  </div>
                );
              })}
            </div>
          </details>
        )}
      </details>
    </div>
  );
}

const AppContent = React.memo(AppContentRaw); // memo: protects against transcript/state-driven parent re-renders.

export default function App() {
  // Remount key for AppContent (still honors "new-thread" window events).
  const [viewKey, setViewKey] = useState(0);

  useEffect(() => {
    const handler = () => setViewKey((k) => k + 1);
    window.addEventListener("new-thread", handler);
    return () => window.removeEventListener("new-thread", handler);
  }, []);

  return <AppContent key={viewKey} />;
}
