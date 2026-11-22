/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
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
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * The orchestrator's conversation.
 *
 * Deliberately separate from `useAISDKChat`: that hook carries berg's
 * session machinery (a server session id, steering a live run, delegation
 * approvals) which belongs to the *Python* chat agent. The orchestrator is a
 * different agent with its own conversation and its own run — a
 * `WorkflowAgent` in this Next app — so it gets one thin hook over
 * `POST /api/orchestrator` rather than borrowing machinery that would send
 * its turns to the wrong place.
 *
 * One `useChat`, one transport. Anything the two eventually share should be
 * extracted from both, not bolted onto one.
 */

"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, generateId, type UIMessage } from "ai";
import { useCallback, useEffect, useRef, useState } from "react";

/** What the page needs to render and drive the orchestrator. */
export interface UseOrchestratorChatReturn {
  /** The conversation, as the UI holds it. */
  messages: UIMessage[];
  /** Whether a turn is in flight. */
  isStreaming: boolean;
  /** The last error, if a turn failed outright. */
  error: string | null;
  /** Send the user's next message and start a turn. */
  send: (text: string) => Promise<void>;
  /** Stop the in-flight turn, if any. */
  stop: () => void;
  /** The workflow run id of the last turn, once the server reports it. */
  lastRunId: string | null;
  /** Approvals the orchestrator is waiting on, one per paused tool call. */
  pendingApprovals: PendingApprovalRequest[];
  /** Answer one: let the paused call run, or refuse it. */
  answerApproval: (approvalId: string, approved: boolean) => void;
  /** The model this run's brain is using. */
  model: string;
  /** Choose which model the orchestrator itself runs on. */
  setModel: (model: string) => void;
}

/** One paused tool call, as the page needs it to ask the user. */
export interface PendingApprovalRequest {
  /** The id to answer. */
  approvalId: string;
  /** Which tool is waiting. */
  toolName: string;
  /** The arguments it intends to use, so the user can judge. */
  input: unknown;
}

/**
 * A failed turn, in words a person can act on.
 *
 * The SDK's raw text is provider-layer plumbing ("Response stream ended without
 * a finish reason"), which tells the user neither what happened nor what to do.
 * Two conditions are worth naming, because both are ordinary:
 *
 * - the model's stream closed mid-answer — common with a local model, and
 *   recoverable by sending again;
 * - a network drop — same advice.
 *
 * Anything else is passed through: an unexplained failure is more useful shown
 * as it was than paraphrased into something vaguer.
 *
 * @param error - The error the SDK reported.
 * @returns What to show the user.
 */
function describeTurnError(error: unknown): string {
  const raw = String((error as { message?: unknown })?.message ?? error);
  if (/ended without a finish reason/i.test(raw)) {
    return (
      "The model's reply ended without finishing — its stream closed " +
      "mid-answer, which a local model does when it stops early or its " +
      "connection drops. Send again to continue; if it keeps happening, " +
      "the model or its endpoint is the thing to look at."
    );
  }
  if (/fetch failed|network|ECONNREFUSED|terminated/i.test(raw)) {
    return `Lost contact while streaming: ${raw}. Send again to continue.`;
  }
  return raw;
}

/**
 * Drive the orchestrator's conversation.
 *
 * @param resumeRunId - A run to adopt as this conversation on mount, so a
 * reloaded page picks up a past orchestration instead of starting empty. Omit
 * it for a fresh conversation.
 * @returns The messages, the send/stop controls, and the last run id.
 */
export function useOrchestratorChat(
  resumeRunId?: string,
): UseOrchestratorChatReturn {
  // The run id arrives on a response header, which the transport sees but
  // React does not — the callback fires outside render. State (not a ref) is
  // what makes the page re-render with the id once it lands.
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  // The same id, readable from a callback created in an earlier render. The
  // reconnect callback is one of those: it fires on a network event long after
  // the transport was built, and it needs the CURRENT session to address the
  // right run rather than the one this render started with.
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    sessionIdRef.current = lastRunId;
  }, [lastRunId]);
  // Which brain this conversation runs on. Empty means the configured
  // default, so a user who never chooses behaves as before.
  const [model, setModel] = useState<string>("");
  // The chosen model, readable by a callback created in an earlier render:
  // a transport callback captures one render's closures, so the ref is what
  // keeps the latest choice reachable. Written after commit rather than
  // during render (react-hooks/refs forbids the latter): the only reader
  // is the send body below, which runs after mount, so the timing is the
  // same as the per-render write it replaces.
  const modelRef = useRef<string>("");
  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  const {
    messages,
    setMessages,
    sendMessage,
    status,
    error,
    stop,
    resumeStream} = useChat({
    // The transport's callbacks can only be attached at construction
    // (the SDK's fields are protected), and they read the model through
    // the ref above because they fire on network events - a send, a
    // reconnect, a minted run id - never during render, so the rule's
    // "access refs outside of render" concern does not apply.
    // eslint-disable-next-line react-hooks/refs
    transport: new DefaultChatTransport({
      // Same origin: this is a Next route in this app, so it needs no
      // API_BASE. Under the `/api/*` proxy this path is explicitly NOT
      // forwarded to Python — filesystem routes win rewrites.
      api: "/api/orchestrator",
      /**
       * Carry the chosen model with every send.
       *
       * Read from the ref rather than closed over, because a model picked
       * mid-conversation must reach the NEXT send, not the one this
       * callback was created during.
       *
       * @param options - The transport's send description.
       * @returns The request body, model included.
       */
      prepareSendMessagesRequest: ({ messages: toSend }) => ({
        body: { messages: toSend, model: modelRef.current }}),
      /**
       * Point the reconnect at where the session's recorded stream lives.
       *
       * Read from the ref rather than the URL's chat id, because a session's
       * address is its WORKFLOW RUN id — that is what the hook is keyed on and
       * what the stream route replays — while the SDK addresses reconnects by
       * its own chat id. The two are the same conversation and different
       * identifiers.
       *
       * Kept for interrupted turns and for the resume below: continuing a
       * stream that was cut off mid-flight, and re-attaching after a follow-up
       * is delivered to a parked run. Restoring a *finished* session does not
       * come through here at all — the page loads berg's stored conversation
       * (lib/orchestrator-turns.ts) and adopts it directly, because a workflow
       * stream records only what the agent wrote.
       *
       * The URL is named rather than derived from `api`, because under
       * `/api/*` a DYNAMIC segment is claimed by the proxy rewrite before
       * its handler runs (measured 2026-11-15), so the replay route sits
       * outside `/api`.
       *
       * @returns The absolute URL to GET, response headers untouched.
       */
      prepareReconnectToStreamRequest: () => ({
        api: `/orchestrator/${sessionIdRef.current ?? ""}/stream`}),
      /**
       * Adopt the workflow run id from the response.
       *
       * The server returns it as `x-workflow-run-id`; keeping it lets a
       * later slice reconnect to a suspended orchestration instead of
       * rebuilding the conversation from nothing.
       *
       * @param options - The transport's fetch options.
       * @returns The fetch response, after the id is recorded.
       */
      fetch: async (input, init) => {
        const response = await fetch(input, init);
        const runId = response.headers.get("x-workflow-run-id");
        // Setting state from a transport callback is safe: the callback
        // runs after the response starts, not during render.
        if (runId) setLastRunId(runId);
        return response;
      }}),
    // Adopting the run means adopting its id: the SDK addresses a reconnect
    // by chat id, and a run id is what identifies the recorded session.
    id: resumeRunId,
    // NO `sendAutomaticallyWhen` here, deliberately.
    //
    // It used to fire on an answered approval, which sent the whole
    // conversation back out as a POST — and that POST STARTED A NEW RUN. That
    // is the defect this session refactor exists to remove: an approval answer
    // launched a sibling session, and the next turn re-planned from the
    // client's view of the past instead of the run's own history. An answer now
    // goes to the run's own hook (`answerApproval` below), which resumes THE
    // SAME run; the client re-attaches to that run's stream afterwards instead
    // of asking the server to start something new.
  });

  /**
   * Send one user message.
   *
   * Two doors, decided by whether this conversation already has a session:
   *
   * - no run id: the first message STARTS a session. The SDK posts to
   *   `/api/orchestrator`, which starts the run and streams its answer, and
   *   the `x-workflow-run-id` header above records the session for later.
   * - a run id: the message RESUMES the session's own run. Posting the
   *   conversation again would start a second run beside the first — which is
   *   what produced 74 runs for a handful of conversations. So the text goes to
   *   the run's hook and the client re-attaches to that run's stream, which
   *   holds everything the session has said since its beginning.
   *
   * The user message is appended locally because a workflow stream records only
   * what the AGENT writes: messages delivered through a hook are not written to
   * it, so without this the transcript would lose its own turns on every
   * reconnect. That is also why the conversation store exists
   * (lib/orchestrator-turns.ts) — the two halves answer different halves of
   * "what did we say".
   *
   * @param text - What the user typed.
   */
  const send = useCallback(
    async (text: string): Promise<void> => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const session = sessionIdRef.current;
      if (!session) {
        await sendMessage({ text: trimmed });
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "user",
          parts: [{ type: "text", text: trimmed }]} as UIMessage]);
      await fetch(`/orchestrator/${encodeURIComponent(session)}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "message", text: trimmed })}).catch(() => undefined);
      // Re-attach to the session's stream: the run continues in it, and the
      // replay carries this turn's answer.
      await resumeStream();
    },
    [sendMessage, setMessages, resumeStream],
  );

  // A paused tool call arrives as a part with state "approval-requested".
  // Surfacing these is what turns the orchestrator's pause into something the
  // user can answer — without it the run stops and nothing can release it.
  const pendingApprovals: PendingApprovalRequest[] = [];
  for (const message of messages) {
    for (const part of message.parts as unknown as Array<
      Record<string, unknown>
    >) {
      if (String(part?.state ?? "") !== "approval-requested") continue;
      // `approval.id` is the field the SDK expects back in
      // addToolApprovalResponse; see the `approval-requested` variant in
      // ai's UIMessage part union.
      const approval = part.approval as { id?: unknown } | undefined;
      const approvalId = String(approval?.id ?? "");
      if (!approvalId) continue;
      pendingApprovals.push({
        approvalId,
        // "tool-start_specialist" -> "start_specialist"
        toolName: String(part.type ?? "").replace(/^tool-/, ""),
        input: part.input ?? part.args ?? null});
    }
  }

  /**
   * Answer a paused tool call.
   *
   * @param approvalId - Which request to answer.
   * @param approved - Whether the call may run.
   */
  // Whether a turn is in flight — the edge the persist below watches.
  const streaming = status === "streaming" || status === "submitted";

  // Persist the conversation when a turn finishes, so a restore has BOTH sides.
  // The turn route already wrote the messages the turn started with; this adds
  // what the agent replied, which that write cannot see because the reply
  // arrives on the stream rather than in the next request. One edge, one route:
  // from streaming to not-streaming, once, with the run id the turn reported.
  const wasStreaming = useRef(false);
  useEffect(() => {
    if (streaming) {
      wasStreaming.current = true;
      return;
    }
    if (!wasStreaming.current || !lastRunId) return;
    wasStreaming.current = false;
    void (async () => {
      try {
        await fetch(`/orchestrator/runs/${encodeURIComponent(lastRunId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages })});
      } catch {
        // A failed write loses the agent's half until the next turn
        // re-writes the whole conversation; it must never break the turn
        // that just finished.
      }
    })();
  }, [streaming, lastRunId, messages]);

  const answerApproval = useCallback(
    (approvalId: string, approved: boolean): void => {
      const session = sessionIdRef.current;
      if (!session) return;

      // The card steps aside locally, in the same shape the SDK would have
      // written, because a replay does not carry the user's decision back: it
      // records model output, not what the user answered.
      setMessages(
        (prev) =>
          prev.map((message) => {
            const parts = message.parts as unknown as Array<
              Record<string, unknown>
            >;
            if (!Array.isArray(parts)) return message;
            let changed = false;
            const nextParts = parts.map((part) => {
              if (
                typeof part !== "object" ||
                part === null ||
                part.state !== "approval-requested"
              ) {
                return part;
              }
              const approval = part.approval as { id?: unknown } | undefined;
              if (approval?.id !== approvalId) return part;
              changed = true;
              return {
                ...part,
                state: "approval-responded",
                approval: { ...approval, approved }};
            });
            return changed ? { ...message, parts: nextParts } : message;
          }) as unknown as UIMessage[],
      );

      void (async () => {
        try {
          await fetch(`/orchestrator/${encodeURIComponent(session)}/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: "approval",
              approvalId,
              approved})});
        } catch {
          // A failed answer leaves the card answered but the run parked. The
          // user's next message still reaches the run, so this must not break
          // the UI.
          return;
        }
        await resumeStream();
      })();
    },
    [setMessages, resumeStream],
  );

  // Restore, on mount only, and in the order that matters: berg's stored
  // conversation first (it holds BOTH sides of the turn), and the durable
  // stream only when there is no stored copy — which is the case for turns
  // sent before the store existed, and for a turn that was cut off mid-flight
  // and never reached its boundary write. Keyed on the run id so a page that
  // opens without one does nothing, and a fresh conversation stays fresh.
  const resumedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!resumeRunId || resumedFor.current === resumeRunId) return;
    resumedFor.current = resumeRunId;
    setLastRunId(resumeRunId);
    void (async () => {
      try {
        const response = await fetch(
          `/orchestrator/runs/${encodeURIComponent(resumeRunId)}`,
        );
        if (response.ok) {
          const data = (await response.json()) as {
            messages?: unknown[];
          };
          if (Array.isArray(data.messages)) {
            // Adopting the conversation wholesale: the transcript is
            // restored as it was, so the next message continues this
            // turn rather than starting a new one beside it.
            setMessages(data.messages as UIMessage[]);
            return;
          }
        }
      } catch {
        // A failed read falls through to the stream below.
      }
      void resumeStream();
    })();
  }, [resumeRunId, resumeStream, setMessages]);

  return {
    messages,
    isStreaming: status === "streaming" || status === "submitted",
    error: error ? describeTurnError(error) : null,
    send,
    stop,
    lastRunId,
    pendingApprovals,
    answerApproval,
    model,
    setModel};
}
