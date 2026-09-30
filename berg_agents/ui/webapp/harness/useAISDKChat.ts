/*
 * Chat hook — wraps AI SDK v7's useChat to talk to the streaming backend.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. This hook provides a clean interface for
 * the App component.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages trigger
 * tool calls (file operations + run_task), which run the full BergAgents harness.
 */

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { UIMessage, TextUIPart } from "ai";
import { useEffect, useState } from "react";
import type { SetStateAction } from "react";
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
}

export interface PendingApproval {
  /** Approval id — pass back to respondToApproval */
  id: string;
  /** Tool the model wants to run (e.g. "write_file") */
  toolName: string;
  /** Human-readable argument summary */
  args: string;
}

export interface UseAISDKChatReturn {
  messages: ChatMessage[];
  input: string;
  /** Direct state setter — compatible with InputBar's setInput prop. */
  setInput: (value: SetStateAction<string>) => void;
  /** Change handler — also compatible with InputBar. */
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
  /** Replace the live conversation (history restore). */
  restoreMessages: (msgs: unknown[]) => void;
  /** Tool calls currently awaiting human approval. */
  pendingApprovals: PendingApproval[];
  /** Answer an approval request; the stream resumes automatically. */
  respondToApproval: (id: string, approved: boolean, reason?: string) => void;
}

/**
 * Extract the model's private reasoning trace from a UIMessage.
 * Reasoning parts (`type: "reasoning"`) carry the chain-of-thought
 * the model streamed before acting — shown collapsed in the UI.
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
 * empty bubbles. Tool invocations are summarized as `🔧 name(args…)`
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
            return `${k}=${s.length > 60 ? s.slice(0, 60) + "…" : s}`;
          });
          args = entries.length > 0 ? `(${entries.join(", ")})` : "";
        } catch {
          args = "";
        }
      }
      // A paused tool call renders as an approval prompt, not a plain call.
      const marker =
        (p as { state?: unknown }).state === "approval-requested"
          ? "⏳ needs approval"
          : "🔧";
      chunks.push(`${marker} ${name}${args}`);
    }
  }
  return chunks.filter(Boolean).join("\n");
}

/**
 * Main chat hook — wraps AI SDK v7's useChat to talk to /api/chat/stream.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages
 * trigger tool calls (file operations + run_task), which run the full
 * BergAgents harness. HITL approval requests surface as tool approval
 * parts in the AI SDK message stream.
 */
export function useAISDKChat(): UseAISDKChatReturn {
  // useChat v7 returns: messages, sendMessage, status, error, setMessages, stop
  // It does NOT return input/handleInputChange/handleSubmit — we manage input
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
      api: `${API_BASE}/api/chat/stream`}),
    // Resume a paused run after the user answers an approval request.
    // Fires only when the last assistant step holds an answered
    // approval (state "approval-responded") with no completed output
    // yet — normal finished turns (all parts "output-available" or
    // plain text) never match, so no spurious re-sends.
    sendAutomaticallyWhen: ({ messages }) => {
      const last = messages[messages.length - 1] as
        { role?: unknown; parts?: unknown } | undefined;
      if (!last || last.role !== "assistant" || !Array.isArray(last.parts)) {
        return false;
      }
      const toolStates: string[] = [];
      for (const part of last.parts) {
        if (typeof part !== "object" || part === null) continue;
        const p = part as { type?: unknown; state?: unknown };
        const t = typeof p.type === "string" ? p.type : "";
        if (t !== "dynamic-tool" && !t.startsWith("tool-")) continue;
        toolStates.push(typeof p.state === "string" ? p.state : "");
      }
      if (!toolStates.some((s) => s === "approval-responded")) return false;
      return toolStates.every((s) =>
        [
          "output-available",
          "output-error",
          "output-denied",
          "approval-responded"].includes(s),
      );
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

  // Answer an approval request. The SDK marks the part responded and
  // re-POSTs the conversation; the backend resumes the paused run.
  const respondToApproval = (
    id: string,
    approved: boolean,
    reason?: string,
  ) => {
    void addToolApprovalResponse({ id, approved, reason });
  };

  // Convert AI SDK UIMessage[] to the simpler ChatMessage[] our UI expects.
  // Reasoning traces ride along separately so the UI can collapse them.
  const messages: ChatMessage[] = uiMessages.map((msg) => ({
    id: msg.id,
    role: msg.role as "user" | "assistant" | "system",
    content: messageText(msg),
    parts: [],
    reasoning: messageReasoning(msg)}));

  const setMessages = (msgs: ChatMessage[]) => {
    setUIMessages(msgs as unknown as UIMessage[]);
  };

  const clearMessages = () => {
    setUIMessages([]);
    try {
      localStorage.removeItem(CHAT_MESSAGES_KEY);
    } catch {
      // Private-mode storage may throw — in-memory state still clears.
    }
  };

  // Restore a snapshot (e.g. from ConversationHistory) into the live chat.
  const restoreMessages = (msgs: unknown[]) => {
    if (!Array.isArray(msgs)) return;
    setUIMessages(msgs as unknown as UIMessage[]);
  };

  // Persist the live conversation so tab switches and reloads keep it.
  useEffect(() => {
    try {
      localStorage.setItem(
        CHAT_MESSAGES_KEY,
        JSON.stringify(uiMessages.slice(-MAX_PERSISTED_MESSAGES)),
      );
    } catch {
      // Quota exceeded or private mode — chat still works in memory.
    }
  }, [uiMessages]);

  // Restore the persisted conversation once, after mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(CHAT_MESSAGES_KEY);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        setUIMessages(parsed as unknown as UIMessage[]);
      }
    } catch {
      // Corrupt storage — start with an empty conversation.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // handleInputChange for a textarea/input — reads e.target.value.
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
    restoreMessages,
    pendingApprovals,
    respondToApproval};
}
