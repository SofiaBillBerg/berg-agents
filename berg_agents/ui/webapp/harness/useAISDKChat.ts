/*
 * Chat hook - wraps AI SDK v7's useChat to talk to the streaming backend.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. This hook provides a clean interface for
 * the App component.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages trigger
 * tool calls (file operations + run_task), which run the full BergAgents harness.
 */

import type { UIMessage, TextUIPart } from "ai";
import type { SetStateAction } from "react";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/envConfig";

/** localStorage key for the live conversation (shared with History). */
export const CHAT_MESSAGES_KEY = "berg_chat_messages";

/** Max messages persisted (keeps quota usage bounded). */
const MAX_PERSISTED_MESSAGES = 200;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  parts?: Array<Record<string, unknown>>;
  /** Model's private reasoning trace (omitted when empty). */
  reasoning?: string;
  /** Completed tool calls, rendered as collapsible cards. */
  toolCalls?: Array<{
    tool: string;
    input?: string;
    output?: string;
    state?: string;
  }>;
}

/** Max output chars kept per tool call for display/export. */
const MAX_TOOL_OUTPUT_CHARS = 4000;

/**
 * Extract completed tool calls from a UIMessage for card rendering.
 * Output text is capped so one giant result cannot flood the chat.
 */
function messageToolCalls(msg: UIMessage): ChatMessage["toolCalls"] {
  const calls: NonNullable<ChatMessage["toolCalls"]> = [];
  for (const part of msg.parts) {
    const p = part as unknown as Record<string, unknown>;
    const pType = typeof p.type === "string" ? p.type : "";
    if (pType !== "dynamic-tool" && !pType.startsWith("tool-")) continue;
    const name =
      (typeof p.toolName === "string" && p.toolName) ||
      (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
    let input = "";
    if (p.input != null) {
      try {
        input =
          typeof p.input === "string"
            ? p.input
            : JSON.stringify(p.input, null, 2);
      } catch {
        input = "";
      }
    }
    let output: string | undefined;
    const raw = (p as { output?: unknown }).output;
    if (raw !== undefined && raw !== null) {
      try {
        output = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
      } catch {
        output = String(raw);
      }
      if (output.length > MAX_TOOL_OUTPUT_CHARS) {
        output = `${output.slice(0, MAX_TOOL_OUTPUT_CHARS)}\n… (output truncated)`;
      }
    }
    calls.push({
      tool: name,
      input: input || undefined,
      output,
      state: typeof p.state === "string" ? (p.state as string) : undefined});
  }
  return calls.length > 0 ? calls : undefined;
}

export interface PendingApproval {
  /** Approval id - pass back to respondToApproval */
  id: string;
  /** Tool the model wants to run (e.g. "write_file") */
  toolName: string;
  /** Human-readable argument summary */
  args: string;
}

export interface UseAISDKChatReturn {
  messages: ChatMessage[];
  input: string;
  /** Direct state setter - compatible with InputBar's setInput prop. */
  setInput: (value: SetStateAction<string>) => void;
  /** Change handler - also compatible with InputBar. */
  handleInputChange: (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => void;
  /** Send the current input message. */
  handleSend: () => void;
  isStreaming: boolean;
  error: string | null;
  isConnected: boolean;
  setMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
  stop: () => void;
  sendMessage: (content: string) => Promise<void>;
  /** Stop the current response, then send (mid-stream steering). */
  interruptWith: (content: string) => Promise<void>;
  /** Replace the live conversation (history restore). */
  restoreMessages: (msgs: unknown[]) => void;
  /** Tool calls currently awaiting human approval. */
  pendingApprovals: PendingApproval[];
  /** Answer one approval (per-item stepwise decisions). */
  respondToApproval: (id: string, approved: boolean, reason?: string) => void;
  /** Answer every pending approval at once (batch convenience). */
  respondToAllApprovals: (approved: boolean, reason?: string) => Promise<void>;
  /** Replace a paused call's args (edit before approving). */
  editApprovalArgs: (id: string, args: unknown) => void;
}

/**
 * Extract the model's private reasoning trace from a UIMessage.
 * Reasoning parts (`type: "reasoning"`) carry the chain-of-thought
 * the model streamed before acting - shown collapsed in the UI.
 */
function messageReasoning(msg: UIMessage): string | undefined {
  const bits: string[] = [];
  for (const part of msg.parts) {
    const p = part as unknown as Record<string, unknown>;
    if (
      typeof p !== "object" ||
      p === null ||
      (p as { type?: unknown }).type !== "reasoning"
    ) {
      continue;
    }
    const text = (p as { text?: unknown }).text;
    if (typeof text === "string" && text.trim() !== "") {
      bits.push(text);
    }
  }
  return bits.length > 0 ? bits.join("\n") : undefined;
}

/**
 * Extract displayable text from a UIMessage's parts (v7 API).
 * In v7, UIMessage has `parts` instead of `content`.
 *
 * Tool-call-only turns carry no text parts, which used to render as
 * empty bubbles. Tool invocations are summarized as `🔧 name(args...)`
 * lines so activity stays visible instead of blank.
 */
function messageText(msg: UIMessage): string {
  const chunks: string[] = [];
  for (const part of msg.parts) {
    if (part.type === "text") {
      chunks.push((part as TextUIPart).text);
      continue;
    }
    // Tool parts: `dynamic-tool` or `tool-<name>` shapes (v7).
    const p = part as unknown as Record<string, unknown>;
    const pType = typeof p.type === "string" ? p.type : "";
    if (pType === "dynamic-tool" || pType.startsWith("tool-")) {
      const name =
        (typeof p.toolName === "string" && p.toolName) ||
        (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
      let args = "";
      if (p.input != null && typeof p.input === "object") {
        try {
          const entries = Object.entries(
            p.input as Record<string, unknown>,
          ).map(([k, v]) => {
            const s = typeof v === "string" ? v : JSON.stringify(v);
            return `${k}=${s}`;
          });
          args = entries.length > 0 ? `(${entries.join(", ")})` : "";
        } catch {
          args = "";
        }
      }
      // Completed calls render as collapsible ToolCards downstream
      // (see messageToolCalls), so the text transcript keeps only a
      // marker for calls still in flight or awaiting approval.
      // (Exports re-attach outputs from `toolCalls` — see utils.)
      const output = (p as { output?: unknown }).output;
      const hasOutput = output !== undefined && output !== null;
      if (!hasOutput) {
        // A paused tool call renders as an approval prompt, not a plain call.
        // Parts without an approval id are ghosts from dead runs (see
        // sanitizeHistory): shown as expired, and the approval card
        // correctly ignores them since there is nothing to answer.
        const approval = (p as { approval?: unknown }).approval as
          { id?: unknown } | undefined;
        const marker =
          (p as { state?: unknown }).state === "approval-requested"
            ? typeof approval?.id === "string"
              ? "⏳ needs approval"
              : "⏳ approval expired"
            : "🔧";
        chunks.push(`${marker} ${name}${args}`);
      }
    }
  }
  return chunks.filter(Boolean).join("\n");
}

/**
 * Sanitize a restored conversation so stale single-use state can never
 * poison a fresh run. Approval responses are per-run nonces: replaying
 * an old `approval-responded` part makes the backend try to resume a
 * dead run (observed as cryptic failures). Parts answered but never
 * executed revert to `approval-requested` so the user is asked again;
 * malformed parts are dropped.
 */
function sanitizeHistory(msgs: unknown[], preserveLatest: boolean): unknown[] {
  return msgs
    .filter(
      (m): m is Record<string, unknown> =>
        typeof m === "object" &&
        m !== null &&
        typeof (m as { id?: unknown }).id === "string" &&
        typeof (m as { role?: unknown }).role === "string" &&
        Array.isArray((m as { parts?: unknown }).parts),
    )
    .map((m, index, all) => {
      if (preserveLatest && index === all.length - 1) return m;
      return {
        ...m,
        parts: (m.parts as unknown[]).filter((p) => {
          if (typeof p !== "object" || p === null) return false;
          const part = p as { type?: unknown; state?: unknown };
          if (typeof part.type !== "string") return false;
          if (
            (part.type === "dynamic-tool" || part.type.startsWith("tool-")) &&
            part.state === "approval-responded" &&
            (part as { output?: unknown }).output === undefined
          ) {
            // Answered but never executed: re-ask instead of replaying.
            return {
              ...part,
              state: "approval-requested",
              approval: undefined};
          }
          return { ...part };
        })};
    });
}

/**
 * Main chat hook - wraps AI SDK v7's useChat to talk to /api/chat/stream.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages
 * trigger tool calls (file operations + run_task), which run the full
 * BergAgents harness. HITL approval requests surface as tool approval
 * parts in the AI SDK message stream.
 */
export function useAISDKChat(): UseAISDKChatReturn {
  // useChat v7 returns: messages, sendMessage, status, error, setMessages, stop
  // It does NOT return input/handleInputChange/handleSubmit - we manage input
  // state separately and call sendMessage directly.
  const [input, setInput] = useState("");

  const {
    messages: uiMessages,
    sendMessage: sdkSendMessage,
    status,
    error,
    setMessages: setUIMessages,
    stop,
    addToolApprovalResponse} = useChat({
    transport: new DefaultChatTransport({
      api: `${API_BASE}/api/chat/stream`,
      // Strip stale approval answers before every send. Anything
      // answered in an EARLIER message belongs to a dead run; only
      // the live last message may carry answers to the backend.
      prepareSendMessagesRequest: ({ id, messages, trigger, messageId }) => ({
        body: {
          id,
          messages: sanitizeHistory(messages as unknown as unknown[], true),
          trigger,
          messageId}})}),
    // Resume a paused run after approvals. Per-item answers mark parts
    // one at a time; the resend fires once every pending part in the
    // paused message is answered (stepwise decisions never fire a
    // partial resume, which the backend rejects). Normal finished
    // turns never match.
    sendAutomaticallyWhen: ({ messages }) => {
      const last = messages[messages.length - 1] as
        { role?: unknown; parts?: unknown } | undefined;
      if (!last || last.role !== "assistant" || !Array.isArray(last.parts)) {
        return false;
      }
      let answered = 0;
      let waiting = 0;
      for (const part of last.parts) {
        if (typeof part !== "object" || part === null) continue;
        const p = part as { type?: unknown; state?: unknown };
        const t = typeof p.type === "string" ? p.type : "";
        if (t !== "dynamic-tool" && !t.startsWith("tool-")) continue;
        if (p.state === "approval-responded") answered += 1;
        else if (p.state === "approval-requested") waiting += 1;
      }
      return answered > 0 && waiting === 0;
    }});

  const isStreaming = status === "streaming" || status === "submitted";

  // Tool calls paused for human approval (HITL). Derived from the raw
  // UI messages: any tool part in state "approval-requested".
  const pendingApprovals: PendingApproval[] = [];
  for (const msg of uiMessages) {
    for (const part of msg.parts) {
      const p = part as unknown as Record<string, unknown>;
      if (
        typeof p !== "object" ||
        p === null ||
        (p as { state?: unknown }).state !== "approval-requested"
      ) {
        continue;
      }
      const approval = (p as { approval?: unknown }).approval as
        { id?: unknown } | undefined;
      const approvalId = typeof approval?.id === "string" ? approval.id : null;
      if (!approvalId) continue;
      const pType = typeof p.type === "string" ? (p.type as string) : "";
      const toolName =
        (typeof p.toolName === "string" && (p.toolName as string)) ||
        (pType.startsWith("tool-") ? pType.slice("tool-".length) : "tool");
      let args = "";
      if (p.input != null && typeof p.input === "object") {
        try {
          args = JSON.stringify(p.input);
        } catch {
          args = "";
        }
      }
      if (!pendingApprovals.some((a) => a.id === approvalId)) {
        pendingApprovals.push({ id: approvalId, toolName, args });
      }
    }
  }

  // Answer ALL pending approvals as one batch. The backend requires
  // a complete answer set (partial answers error with "results need
  // to be provided for all deferred tool calls"), so per-item answers
  // are deliberately not offered: one pause, one decision, one resume.
  const respondToAllApprovals = async (approved: boolean, reason?: string) => {
    const ids = pendingApprovals.map((a) => a.id);
    for (const id of ids) {
      await addToolApprovalResponse({ id, approved, reason });
    }
  };

  // Convert AI SDK UIMessage[] to the simpler ChatMessage[] our UI expects.
  // Reasoning traces and tool calls ride along separately so the UI can
  // collapse them (reasoning block, ToolCards).
  const messages: ChatMessage[] = uiMessages.map((msg) => ({
    id: msg.id,
    role: msg.role as "user" | "assistant" | "system",
    content: messageText(msg),
    parts: [],
    reasoning: messageReasoning(msg),
    toolCalls: messageToolCalls(msg)}));

  const setMessages = (msgs: ChatMessage[]) => {
    setUIMessages(msgs as unknown as UIMessage[]);
  };

  const clearMessages = () => {
    setUIMessages([]);
    try {
      localStorage.removeItem(CHAT_MESSAGES_KEY);
    } catch {
      // Private-mode storage may throw - in-memory state still clears.
    }
  };

  // Restore a snapshot (e.g. from ConversationHistory) into the live chat.
  // Stored snapshots predate this load, so no paused run can be live.
  const restoreMessages = (msgs: unknown[]) => {
    if (!Array.isArray(msgs)) return;
    setUIMessages(sanitizeHistory(msgs, false) as unknown as UIMessage[]);
  };

  // Tracks whether the mount-restore below has run. The persist effect
  // must stay quiet until then: on a fresh mount uiMessages is empty,
  // and persisting that emptiness first would wipe the stored
  // conversation (this is what erased chats on tab switches).
  const restoredRef = useRef(false);

  // Persist the live conversation so tab switches and reloads keep it.
  useEffect(() => {
    if (!restoredRef.current) return;
    try {
      localStorage.setItem(
        CHAT_MESSAGES_KEY,
        JSON.stringify(uiMessages.slice(-MAX_PERSISTED_MESSAGES)),
      );
    } catch {
      // Quota exceeded or private mode - chat still works in memory.
    }
  }, [uiMessages]);

  // Restore the persisted conversation once, after mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(CHAT_MESSAGES_KEY);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        setUIMessages(sanitizeHistory(parsed, false) as unknown as UIMessage[]);
      }
    } catch {
      // Corrupt storage - start with an empty conversation.
    } finally {
      restoredRef.current = true;
    }
  }, []);

  // handleInputChange for a textarea/input - reads e.target.value.
  const handleInputChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    setInput(e.target.value);
  };

  // handleSend sends the current input via AI SDK's sendMessage.
  // Clears the box immediately so the sent text doesn't linger.
  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    const text = input;
    setInput("");
    void sdkSendMessage({ text });
  };

  // Programmatic send (used by App's slash-command handler).
  // Also clears the input box when the sent content matches it.
  const sendMessage = async (content: string) => {
    if (!content.trim() || isStreaming) return;
    setInput((prev) => (prev.trim() === content.trim() ? "" : prev));
    await sdkSendMessage({ text: content });
  };

  // Interrupt-and-redirect: stop the in-flight response, then send.
  // This is how the user steers mid-stream. stop() aborts the fetch;
  // the fresh send opens its own request, so no state gets tangled.
  const interruptWith = async (content: string) => {
    if (!content.trim()) return;
    stop();
    setInput("");
    await sdkSendMessage({ text: content });
  };

  return {
    messages,
    input,
    setInput,
    handleInputChange,
    handleSend,
    isStreaming,
    error: error ? String(error) : null,
    isConnected: true,
    setMessages,
    clearMessages,
    stop,
    sendMessage,
    interruptWith,
    restoreMessages,
    pendingApprovals,
    respondToAllApprovals};
}
