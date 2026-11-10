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
 * Chat hook - wraps AI SDK v7's useChat to talk to the streaming backend.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. This hook provides a clean interface for
 * the App component.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages trigger
 * tool calls (file operations + run_task), which run the full BergAgents harness.
 */

import type { UIMessage } from "ai";
import type { SetStateAction } from "react";
import type { PendingQuestion, PendingQuestionAnswer } from "./askUser";
import type { ChatMessage } from "./messageParts";
import type { PendingApproval } from "./hitl";
import type { FailureNotice } from "./recovery";

import { DefaultChatTransport } from "ai";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";

import { ASK_USER_TOOL_NAME, isQuestionAnswerPayload } from "./askUser";
import { partToolName, toChatMessage } from "./messageParts";
import { sanitizeHistory } from "./history";
import { useSendRecovery } from "./recovery";
import { useRunWatch } from "./runWatch";
import { useServerSessions } from "./sessions";
import { usePendingSteering } from "./steering";
import {
  approvalBatchFrom,
  createHitlResponders,
  pendingApprovalsFrom,
  questionBatchFrom} from "./hitl";
import {
  answerDelegatedQuestion,
  delegationQuestionsFrom,
  type DelegationQuestion} from "./delegationQuestions";
import {
  storeSessionId} from "./sessionIdentity";

import { API_BASE } from "@/envConfig";

export type { ChatMessage } from "./messageParts";

/* The active session id and its storage live in ./sessionIdentity. */

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
  steer: (content: string) => Promise<void>;
  /** Messages the agent has not read yet (the steering strip above the
   * input). An entry here is queued on the server's run; once the model
   * receives it, it moves into the transcript and leaves this list. */
  pendingSteering: string[];
  /** Replace the live conversation (history restore). */
  restoreMessages: (msgs: unknown[]) => void;
  /** Tool calls currently awaiting user approval. */
  pendingApprovals: PendingApproval[];
  /** Full active approval batch from the last assistant message: pending
     plus already-decided items (decided items stay visible with badges
     + undo until the resume fires and parts transition to output). */
  approvalBatch: PendingApproval[];
  /** Answer one approval (per-item stepwise decisions). */
  respondToApproval: (id: string, approved: boolean, reason?: string) => void;
  /** Answer a delegated task's gated write from its own card. */
  resolveDelegatedApproval: (id: string, approved: boolean) => Promise<void>;
  /** Answer every pending approval at once (batch convenience). */
  respondToAllApprovals: (approved: boolean, reason?: string) => Promise<void>;
  /** Replace a paused call's args (edit before approving). */
  editApprovalArgs: (id: string, args: unknown) => void;
  /** Withdraw a per-item decision before the batch resumes. */
  revertApproval: (id: string) => void;
  /** Full active question batch from the last assistant message:
     pending calls plus already-answered ones (answered calls show a
     badge until the resume fires and the server overwrites their
     outputs with the rendered results). */
  questionBatch: PendingQuestion[];
  /** A delegated sub-agent's question, waiting for the user. */
  delegationQuestions: DelegationQuestion[];
  /** Answer it. Resolves true when the task was still waiting. */
  answerDelegation: (taskId: string, answer: string) => Promise<boolean>;
  /** Answer one ask_user_question call: its answers, or a decline. */
  respondToQuestion: (
    id: string,
    answers: PendingQuestionAnswer[],
    declined: boolean,
  ) => void;
  /** Decline every pending question in the batch at once. */
  declineAllQuestions: () => void;
  /** The active failure notice, or null: the one input to the
   * failure dialog. Replaces the old systemNotice alert - its
   * recovery content is now the "recovery" kind here. */
  failureNotice: FailureNotice | null;
  /** Dismiss the failure dialog (read and acknowledged). */
  dismissFailureNotice: () => void;
  /** Retry the last failed user send (send-kind failures only). */
  retryLast: () => void;
  /** Active server-side session id (source of truth across browsers). */
  sessionId: string | null;
  /** Active session title for the chrome row. */
  sessionTitle: string | null;
  /** Start a new server-side session (clears the live chat). */
  newServerChat: () => Promise<void>;
  /** Open a server-side session by id (loads its transcript). */
  openSession: (id: string) => Promise<void>;
}

/* History hygiene (what a restore or a send may echo back)
 * lives in ./history - see sanitizeHistory. */

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

  // The transport's callbacks fire outside React's render - a minted
  // session id arrives on a fetch, a reconnect happens later - so they
  // reach the session handle through refs refreshed each render instead
  // of capturing one render's closures. The handle itself lives in
  // ./sessions and is created after useChat, because it needs the SDK's
  // message setter.
  const adoptSessionRef = useRef<(id: string | null) => void>(
    () => {},
  );
  const sessionIdHolderRef = useRef<{ current: string | null }>({
    current: null});

  const {
    messages: uiMessages,
    sendMessage: sdkSendMessage,
    status,
    error,
    setMessages: setUIMessages,
    stop,
    addToolApprovalResponse,
    // Writes a question answer into a tool part's output (matches by
    // toolCallId in any state, rewrites to output-available, then
    // re-evaluates sendAutomaticallyWhen - which resumes the run once
    // every pending part is answered).
    addToolOutput,
    // Follow a run that is still going without sending anything: the GET
    // stream replays the run's journal, so a reload or a second tab
    // rebuilds the same turn.
    resumeStream: sdkResumeStream} = useChat({
    // Recovering a run is this hook's job below, gated on the server's
    // status. The SDK's built-in `resume` recovers only after a network
    // disconnect and would otherwise resume on every mount.
    resume: false,
    transport: new DefaultChatTransport({
      api: `${API_BASE}/api/chat/stream`,
      // Strip stale approval answers before every send. Anything
      // answered in an EARLIER message belongs to a dead run; only
      // the live last message may carry answers to the backend.
      // sessionId tells the backend which server-side session this
      // turn belongs to (any browser, any profile).
      prepareSendMessagesRequest: ({ id, messages, trigger, messageId }) => ({
        body: {
          id,
          // Latest message goes out exactly as the client has it -
          // steering above all. The old "the newest user message is
          // what we're sending" reading was wrong once the client
          // echoed its whole list back: a message typed mid-run
          // arrives as the SECOND-to-last user message, behind the
          // assistant turn that is still growing.
          messages: sanitizeHistory(messages as unknown as unknown[], true),
          trigger,
          messageId,
          sessionId}}),
      // Where a follow request goes. The run lives on the server, so
      // following is a plain GET at that session's stream - never a
      // re-send of the last message.
      prepareReconnectToStreamRequest: () => ({
        api: `${API_BASE}/api/chat/stream?session=${encodeURIComponent(
          sessionIdHolderRef.current.current ?? "",
        )}`}),
      // A fresh chat sends no id and the server mints one; the id comes
      // back as a response header, and this is where the client adopts
      // it. Without this the page would keep sending empty ids - each
      // would mint a brand-new session - and Stop/follow would address
      // nothing until a reload. Storing here (not in an effect) keeps
      // the very next send on the same session.
      fetch: async (input, init) => {
        const resp = await fetch(input, init);
        const minted = resp.headers.get("x-berg-session-id");
        if (minted && minted !== sessionIdHolderRef.current.current) {
          adoptSessionRef.current(minted);
          storeSessionId(minted);
        }
        return resp;
      }}),
    // Resume a paused run after approvals or question answers. Both
    // kinds mark their parts one at a time; the resend fires once
    // every pending part in the paused message is answered (stepwise
    // decisions never fire a partial resume, which the backend
    // rejects). Normal finished turns never match:
    // - approvals count as answered in "approval-responded";
    // - a question counts as answered in "output-available" with the
    //   canonical answer payload in its output (see
    //   isQuestionAnswerPayload) - after the resume the server
    //   overwrites that output with the rendered result, which the
    //   shape check rejects, so a completed turn cannot re-fire;
    // - a question counts as waiting in "input-available" (live
    //   wire) and "approval-requested" (a reload's dump marks every
    //   deferred call that way).
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
        const p = part as unknown as Record<string, unknown>;
        const t = typeof p.type === "string" ? p.type : "";
        if (t !== "dynamic-tool" && !t.startsWith("tool-")) continue;
        if (partToolName(p) === ASK_USER_TOOL_NAME) {
          if (
            p.state === "output-available" &&
            isQuestionAnswerPayload(p.output)
          ) {
            answered += 1;
          } else if (
            p.state === "input-available" ||
            p.state === "approval-requested"
          ) {
            waiting += 1;
          }
        } else {
          if (p.state === "approval-responded") answered += 1;
          else if (p.state === "approval-requested") waiting += 1;
        }
      }
      return answered > 0 && waiting === 0;
    }});

  // The session this chat belongs to - its identity and the four ways it
  // changes. Created here because it needs the SDK's message setter;
  // the transport above reaches it through the refs it was given.
  const {
    sessionId,
    sessionTitle,
    setSessionTitle,
    sessionIdRef,
    adoptSession,
    restoreMessages,
    reloadSession,
    openSession,
    newServerChat} = useServerSessions({
    apiBase: API_BASE,
    setUIMessages});
  adoptSessionRef.current = adoptSession;
  sessionIdHolderRef.current = sessionIdRef;

  const isStreaming = status === "streaming" || status === "submitted";

  // Steering the agent has not read yet - the queue the transcript
  // cannot show. Sampled from the server, because the server owns the
  // answer (see ./steering).
  const {pendingSteering, setPendingSteering} = usePendingSteering({
    sessionId,
    isStreaming,
    apiBase: API_BASE});

  // Tool calls paused for human approval (HITL), and the answers that
  // release them. The derivations and responders live in ./hitl; the
  // factory is rebuilt per render so the responders read the messages
  // the user is looking at.
  const pendingApprovals = pendingApprovalsFrom(uiMessages);
  const approvalBatch = approvalBatchFrom(uiMessages);
  const questionBatch = questionBatchFrom(uiMessages);
  // A delegated sub-agent's question. Its own derivation, for the same
  // reason ask_user's is: the part shape lives in one module and the
  // responder is built next to the derivation that feeds it.
  const delegationQuestions = delegationQuestionsFrom(uiMessages);
  const {
    respondToApproval,
    respondToAllApprovals,
    resolveDelegatedApproval,
    editApprovalArgs,
    revertApproval,
    respondToQuestion,
    declineAllQuestions} = createHitlResponders({
    messages: uiMessages,
    addToolApprovalResponse,
    addToolOutput,
    setMessages: setUIMessages});

  // Answering a delegated task's question. Unlike the ask_user batch this
  // writes no part: the task holds the waiting question, so the answer
  // travels to the server and the task's own stream carries on. The
  // session id is read at call time rather than closed over, so an answer
  // sent after a session switch still names the run that asked.
  const answerDelegation = useCallback(
    async (taskId: string, answer: string) => {
      if (!sessionId) return false;
      return answerDelegatedQuestion(sessionId, taskId, answer);
    },
    [sessionId],
  );

  // Convert AI SDK UIMessage[] to the simpler ChatMessage[] our UI expects.
  // One walk per message fills all three renderings (text, reasoning,
  // tool calls) - the parts shapes live in ./messageParts.
  const messages: ChatMessage[] = uiMessages.map(toChatMessage);

  const setMessages = (msgs: ChatMessage[]) => {
    setUIMessages(msgs as unknown as UIMessage[]);
  };

  const clearMessages = () => {
    setUIMessages([]);
  };



  // Failed-send recovery and the one failure surface - both live in
  // ./recovery. resetRecovery is what a new send calls: the user is
  // driving again, so the ids auto-rejected by the previous failure
  // are forgotten.
  const {
    failureNotice,
    setFailureNotice,
    resetRecovery} = useSendRecovery({
    error,
    uiMessages,
    status,
    addToolApprovalResponse});

  // The backend refines a generated title once the first real user
  // message arrives (a greeting leaves it as "#N · date"), so the
  // header must re-read it after a settled turn. Without this the
  // title stays whatever it was at create time.
  useEffect(() => {
    if (!sessionId) return;
    if (isStreaming) return;
    let cancelled = false;
    const reverifyTitle = async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`,
        );
        if (!resp.ok || cancelled) return;
        const data = await resp.json();
        if (
          !cancelled &&
          data.session &&
          typeof data.session.title === "string" &&
          data.session.title !== sessionTitle
        ) {
          setSessionTitle(data.session.title);
        }
      } catch {
        // Backend unreachable - the existing title stands.
      }
    };
    void reverifyTitle();
    return () => {
      cancelled = true;
    };
  }, [sessionId, sessionTitle, isStreaming]);



  // Follow and account for this session's runs from any tab, and check
  // how a run this client SENT ended - both in ./runWatch. stopFollowing
  // is what an explicit Stop calls: the run ended for good.
  const {stopFollowing} = useRunWatch({
    sessionId,
    isStreaming,
    apiBase: API_BASE,
    resumeStream: sdkResumeStream,
    reloadSession,
    setFailureNotice,
    setPendingSteering});

  // The last user text that was sent, for "Retry last" on a failed
  // send. Updated on every manual send; the retry re-sends it verbatim.
  // It belongs to the send paths here, not to ./recovery: the recovery
  // effect only ever rejects approvals, it never re-sends.
  const lastSentTextRef = useRef<string | null>(null);

  // handleInputChange for a textarea/input - reads e.target.value.
  const handleInputChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
  ) => {
    setInput(e.target.value);
  };

  // handleSend sends the current input via AI SDK's sendMessage.
  // Clears the box immediately so the sent text doesn't linger.
  // A manual send resets recovery state: the user is driving again.
  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    const text = input;
    setInput("");
    setFailureNotice(null);
    lastSentTextRef.current = text;
    resetRecovery();
    void sdkSendMessage({ text });
  };

  // Programmatic send (used by App's slash-command handler).
  // Also clears the input box when the sent content matches it.
  const sendMessage = async (content: string) => {
    if (!content.trim() || isStreaming) return;
    setInput((prev) => (prev.trim() === content.trim() ? "" : prev));
    setFailureNotice(null);
    lastSentTextRef.current = content;
    resetRecovery();
    await sdkSendMessage({ text: content });
  };

  // Retry the last user text after a failed send: the words are what
  // the user last chose to say, so "Retry last" must not re-type them
  // by hand. No new failure clears (the next failure replaces), and a
  // retry resets recovery so the auto-reject round is available again.
  const retryLast = () => {
    const text = lastSentTextRef.current;
    if (!text || isStreaming) return;
    setFailureNotice(null);
    resetRecovery();
    void sdkSendMessage({ text });
  };

  // Steer, never interrupt. A message sent while the agent is working joins
  // the run and reaches the model at its NEXT request; the in-flight tool is
  // never aborted. The server decides whether the run is live (it owns the
  // run), so one send path covers both the steer and the fresh turn.
  const steer = async (content: string) => {
    if (!content.trim()) return;
    setInput("");
    setFailureNotice(null);
    await sdkSendMessage({ text: content });
  };

  // Stop is an explicit act, and the run no longer belongs to this fetch:
  // aborting the request would only stop *reading* it. So stop tells the
  // server to end the run, then drops the local stream. Everything the run
  // completed is kept (the server persists the turn either way).
  const stopRun = useCallback(() => {
    // Read through the ref: this callback must stop the session that is
    // current NOW, not the one that existed when it was created.
    const id = sessionIdRef.current;
    // An explicit Stop ends the run for good: nothing left to follow.
    stopFollowing();
    // And nothing will be read in this turn, so the strip goes with the
    // run. The steer itself is not lost: the server persists it into the
    // turn's record, where the reloaded transcript shows it.
    setPendingSteering([]);
    // Keep the turn up to here - it may hold a steer the model has not
    // read, the approval card, or text already streamed - but mark it
    // closed so it stops looking like it is still being written.
    setUIMessages(
      (msgs) =>
        msgs.map((m) => {
          if (m.role !== "assistant") return m;
          // Not every part kind carries a state; only the ones that
          // stream text, reasoning or tool input do.
          const parts = m.parts.map((p) => {
            const state = (p as { state?: unknown }).state;
            return state === "streaming"
              ? ({ ...p, state: "done" } as typeof p)
              : p;
          });
          const changed = parts.some((p, i) => p !== m.parts[i]);
          return changed ? { ...m, parts } : m;
        }) as unknown as UIMessage[],
    );
    if (id) {
      void fetch(
        `${API_BASE}/api/chat/stop?session=${encodeURIComponent(id)}`,
        { method: "POST" },
      ).catch(() => {
        // Backend unreachable: the local stop still applies.
      });
    }
    stop();
  }, [stop]);

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
    stop: stopRun,
    sendMessage,
    steer,
    pendingSteering,
    restoreMessages,
    pendingApprovals,
    approvalBatch,
    respondToApproval,
    respondToAllApprovals,
    resolveDelegatedApproval,
    editApprovalArgs,
    revertApproval,
    questionBatch,
    respondToQuestion,
    declineAllQuestions,
    delegationQuestions,
    answerDelegation,
    failureNotice,
    dismissFailureNotice: () => setFailureNotice(null),
    retryLast,
    sessionId,
    sessionTitle,
    newServerChat,
    openSession};
}
