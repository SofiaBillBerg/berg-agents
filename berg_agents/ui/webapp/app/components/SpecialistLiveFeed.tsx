"use client";

// A specialist's work, streaming live into the orchestrator's transcript.
//
// The Subagent pattern's "Running" section: while the subagent runs, the
// row's content shows the tool calls so far. berg's specialist reports
// through its own durable stream, so this tails that stream and folds it
// with the same renderer the chat uses — one protocol, one look. The
// stream is re-opened whenever it closes, so a turn whose passes end and
// resume (every gate) keeps streaming without the reader doing anything.

import type { ChatMessage } from "@/harness";

import { useEffect, useRef, useState } from "react";

import { MessageList } from "./MessageList.tsx";

import { API_BASE } from "@/envConfig";
import { toChatMessage } from "@/harness/messageParts";

/** One SSE frame's payload, as berg's encoder writes it. */
interface StreamFrame {
  type?: string;
  id?: string;
  [key: string]: unknown;
}

/**
 * Fold a raw frame into the parts being collected for its message.
 *
 * The protocol is the AI SDK's own: deltas append to a part started by
 * `*-start`, and tool parts arrive whole. Only the part kinds the
 * transcript renders are kept, so the feed stays one derivation of what
 * the specialist did rather than a second protocol.
 *
 * Tool frames carry no message id of their own — they belong to the
 * message whose parts were streaming when they arrived, which is the
 * last id the stream named. The caller passes that id in.
 *
 * @param frame - One parsed SSE frame.
 * @param parts - The parts collected so far, keyed by message id.
 * @param currentId - The last message id the stream named.
 * @returns The message id this frame belonged to.
 */
function foldFrame(
  frame: StreamFrame,
  parts: Map<string, unknown[]>,
  currentId: string,
): string {
  const type = frame.type ?? "";
  // A named id is this frame's message; a bare tool frame continues the
  // message that was streaming.
  const messageId =
    typeof frame.id === "string" && frame.id ? frame.id : currentId;
  if (!messageId) return currentId;
  const list = parts.get(messageId) ?? [];
  parts.set(messageId, list);
  // The part the next delta continues, when there is one.
  const last = list[list.length - 1] as Record<string, unknown> | undefined;

  if (type === "reasoning-delta") {
    const delta = (frame.delta as string) ?? "";
    if (last?.type === "reasoning") {
      last.text = `${(last.text as string) ?? ""}${delta}`;
    } else {
      list.push({ type: "reasoning", text: delta });
    }
    return;
  }
  if (type === "text-delta") {
    const delta = (frame.delta as string) ?? "";
    if (last?.type === "text") {
      last.text = `${(last.text as string) ?? ""}${delta}`;
    } else {
      list.push({ type: "text", text: delta });
    }
    return;
  }
  if (type === "tool-input-start") {
    list.push({
      type: `tool-${frame.toolName ?? "tool"}`,
      toolCallId: frame.toolCallId,
      state: "input-streaming",
      input: {}});
    return;
  }
  if (type === "tool-input-available") {
    const existing = list.find(
      (part) =>
        (part as { toolCallId?: unknown }).toolCallId === frame.toolCallId,
    ) as Record<string, unknown> | undefined;
    if (existing) {
      existing.input = frame.input;
      existing.state = "input-available";
    } else {
      list.push({
        type: `tool-${frame.toolName ?? "tool"}`,
        toolCallId: frame.toolCallId,
        state: "input-available",
        input: frame.input});
    }
    return;
  }
  if (type === "tool-output-available") {
    const existing = list.find(
      (part) =>
        (part as { toolCallId?: unknown }).toolCallId === frame.toolCallId,
    ) as Record<string, unknown> | undefined;
    if (existing) {
      existing.output = frame.output;
      existing.state = "output-available";
    }
    return;
  }
  if (type === "tool-output-error" || type === "tool-input-error") {
    const existing = list.find(
      (part) =>
        (part as { toolCallId?: unknown }).toolCallId === frame.toolCallId,
    ) as Record<string, unknown> | undefined;
    if (existing) {
      existing.errorText = frame.errorText ?? "";
      existing.state = "output-error";
    }
  }
}

/**
 * The specialist's live stream, folded into the transcript's own shape.
 *
 * @param props - The specialist's run id.
 * @returns The streaming transcript, or nothing before the first frame.
 */
export default function SpecialistLiveFeed({
  runId,
  live}: {
  runId: string;
  /** Whether the specialist's turn is still live. A finished turn's
      journal is not going to grow, so re-opening its stream would be a
      pure drain, and the reconnect loop stops. */
  live: boolean;
}) {
  // The fold is kept in a ref so a new frame does not rebuild state from
  // scratch; the rendered messages are the ref's projection, taken on
  // every frame.
  const partsRef = useRef<Map<string, unknown[]>>(new Map());
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    if (!runId || !live) return;
    let cancelled = false;

    // A finished turn's journal is not going to grow, so re-opening its
    // stream is a pure drain on the backend: the reconnect loop stops
    // once the turn settles. While it IS live the loop keeps the row
    // streaming, with a backoff so a pause costs one retry, not five a
    // second.
    let backoffMs = 1000;
    const MAX_BACKOFF_MS = 15000;

    const open = async (): Promise<void> => {
      try {
        // Straight at the backend when the env names one: the /api/*
        // rewrite proxies non-streaming calls fine but never delivers an
        // SSE body to a fetch reader (verified: curl through the proxy
        // gets the whole journal, `fetch` hangs with zero chunks), and
        // envConfig's API_BASE is the same origin the chat page streams
        // from. Relative stays the fallback for the single-origin build.
        const streamUrl = API_BASE
          ? `${API_BASE}/api/workflow/chat/${encodeURIComponent(runId)}/stream`
          : `/api/workflow/chat/${encodeURIComponent(runId)}/stream`;
        const response = await fetch(streamUrl);
        if (!response.ok || !response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentId = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done || cancelled) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE frames are separated by a blank line.
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const raw = buffer.slice(0, boundary).trim();
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
            if (!raw.startsWith("data:")) continue;
            const payload = raw.slice(5).trim();
            if (payload === "[DONE]") continue;
            try {
              // The fold returns the message the stream is on, so a
              // following tool frame (which names no id) lands in it.
              currentId = foldFrame(
                JSON.parse(payload) as StreamFrame,
                partsRef.current,
                currentId,
              );
              setMessages(
                [...partsRef.current.entries()].map(([id, parts]) =>
                  toChatMessage({ id, role: "assistant", parts } as never),
                ),
              );
            } catch {
              // A torn frame is dropped: the next one carries on.
            }
          }
        }
      } catch {
        // A dropped connection is re-opened below rather than surfaced:
        // a live feed that errors on a blink is not live.
      } finally {
        if (!cancelled) {
          // The stream closes when a pass ends; the turn continues (a
          // gate answer, a steer), so re-open — with a backoff, and only
          // while the turn is live.
          window.setTimeout(() => void open(), backoffMs);
          backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
        }
      }
    };

    void open();
    return () => {
      cancelled = true;
    };
  }, [runId, live]);

  if (messages.length === 0) return null;
  return <MessageList history={messages} isAnimating={true} />;
}
