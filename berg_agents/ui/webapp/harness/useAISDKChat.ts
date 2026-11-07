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

import { DefaultChatTransport } from "ai";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";

import { ASK_USER_TOOL_NAME, isQuestionAnswerPayload } from "./askUser";
import { partToolName, toChatMessage } from "./messageParts";
import { sanitizeHistory, SYSTEM_RETRY_REASON } from "./history";
import { useServerSessions } from "./sessions";
import {
  approvalBatchFrom,
  createHitlResponders,
  pendingApprovalsFrom,
  questionBatchFrom} from "./hitl";
import {
  storeSessionId} from "./sessionIdentity";

import { API_BASE } from "@/envConfig";

export type { ChatMessage } from "./messageParts";

/* The active session id and its storage live in ./sessionIdentity. */

// Client-side hint for transport failures - the one failure class whose
// cause the client can see better than the server (it never reached the
// backend). Provider-level diagnosis stays server-side and arrives on the
// run's status; the client never duplicates that matching logic.
function clientFailureHint(detail: string): string | undefined {
  if (/fetch|network|econn|connection|refused|timeout/i.test(detail)) {
    return "The chat backend could not be reached — is the server running?";
  }
  return undefined;
}

/**
 * One failure the failure dialog presents. The dialog is the ONE
 * surface for fatal failures (a warning toast + a hidden debug line
 * used to duplicate it); the journal text in the transcript is the
 * separate durable record and stays.
 */
export interface FailureNotice {
  /** Which class of failure this is - the dialog titles on it. */
  kind: "send" | "run" | "recovery";
  /** The raw error text, truncated for display. */
  detail: string;
  /**
   * Actionable hint, when one is known. Server-side failures carry the
   * backend's hint (one hint logic, no client duplication); client-side
   * failures derive a network hint from the error text.
   */
  hint?: string;
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
  // Whether this client is currently subscribed to a run it did not start
  // (after a reload, a tab switch, or a second browser).
  const isFollowingRef = useRef(false);
  // The last settled run this tab has accounted for (reloaded its
  // transcript, reported its failure once): a session key plus a
  // fingerprint of the settled status. ``null`` means the tab has not
  // looked yet; ``fingerprint: ""`` means it has looked and the session
  // was idle-clean at that moment, so any settled run seen later is
  // unambiguously news.
  const settledRunRef = useRef<{ session: string; fingerprint: string } | null>(
    null,
  );

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

  // Steering the agent has not read yet. This is the queue the transcript
  // cannot show: a message that exists on the server's run but not in the
  // model's view. The server owns the answer, so it is sampled rather than
  // guessed from optimistic sends, and it is empty whenever that is true.
  const [pendingSteering, setPendingSteering] = useState<string[]>([]);
  useEffect(() => {
    if (!sessionId) {
      setPendingSteering([]);
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
        );
        if (!resp.ok || cancelled) return;
        const data = (await resp.json()) as {
          live?: unknown;
          steering?: unknown;
        };
        // The strip means "the agent is about to read this". Once the
        // run is over nothing will be read in this turn, so the strip
        // empties rather than outliving the run that gave it meaning.
        const queued =
          data.live === true && Array.isArray(data.steering)
            ? data.steering.filter((t): t is string => typeof t === "string")
            : [];
        if (!cancelled) setPendingSteering(queued);
      } catch {
        // Backend unreachable - keep showing what we know.
      }
    };
    void poll();
    // Nothing to poll when no run is live; the strip is only ever
    // non-empty inside a run.
    if (!isStreaming)
      return () => {
        cancelled = true;
      };
    const timer = setInterval(() => void poll(), 1200);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId, isStreaming]);

  // Tool calls paused for human approval (HITL), and the answers that
  // release them. The derivations and responders live in ./hitl; the
  // factory is rebuilt per render so the responders read the messages
  // the user is looking at.
  const pendingApprovals = pendingApprovalsFrom(uiMessages);
  const approvalBatch = approvalBatchFrom(uiMessages);
  const questionBatch = questionBatchFrom(uiMessages);
  const {
    respondToApproval,
    respondToAllApprovals,
    editApprovalArgs,
    revertApproval,
    respondToQuestion,
    declineAllQuestions} = createHitlResponders({
    messages: uiMessages,
    addToolApprovalResponse,
    addToolOutput,
    setMessages: setUIMessages});

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



  // Visible notice for the failure dialog. A failure is transient UI on
  // top of the durable record: the journal text in the transcript is
  // what survives (and reloads); the dialog demands to be read once.
  // Recovery actions the system took (auto-rejected approvals) ride in
  // the notice too, so there is exactly one failure surface.
  const [failureNotice, setFailureNotice] = useState<FailureNotice | null>(
    null,
  );
  // The last user text that was sent, for "Retry last" on a failed
  // send. Updated on every manual send; the retry re-sends it verbatim.
  const lastSentTextRef = useRef<string | null>(null);

  // Failed-send recovery: the backend is stateless, so any approval
  // parts pending when a send errors belong to a run that can never
  // resume — replaying them only reproduces the mismatch error
  // forever. Auto-reject them with the retry-friendly system reason
  // (NOT the firm user-rejection text) and tell the user visibly;
  // sendAutomaticallyWhen then resumes and the model may retry.
  // Already-handled ids are never touched twice, so a persistently
  // failing backend cannot loop sends forever.
  const handledErrorRef = useRef<unknown>(null);
  const autoRejectedIds = useRef<Set<string>>(new Set());
  // Hard stop on the recovery loop itself. Each auto-reject mints NEW
  // approval ids, so an id set can never bound this: reject → auto-resume →
  // fail → reject again is an unbounded message storm (observed: ~100
  // messages in seconds). After one failed recovery round the loop is
  // disarmed and the next step needs a human send.
  const recoveryRoundsRef = useRef(0);
  useEffect(() => {
    if (!error) {
      // A clean turn in between proves the pipeline works again.
      recoveryRoundsRef.current = 0;
      return;
    }
    if (handledErrorRef.current === error) return;
    handledErrorRef.current = error;
    // A stale deferred answer (HTTP 409) is the designed card-expiry
    // path, not a failure: the run being answered already ended, so
    // there is nothing to diagnose. It must never open the dialog.
    if ((error as { statusCode?: number }).statusCode === 409) return;
    if (recoveryRoundsRef.current >= 1) {
      setFailureNotice({
        kind: "recovery",
        detail: `Send keeps failing (${String(error).slice(0, 160)}).`,
        hint: "Automatic recovery stopped after one round — send a new message to try again."});
      return;
    }
    recoveryRoundsRef.current += 1;
    const ids: string[] = [];
    for (const msg of uiMessages) {
      if (msg.role !== "assistant" || !Array.isArray(msg.parts)) continue;
      for (const part of msg.parts) {
        const p = part as unknown as Record<string, unknown>;
        if (
          typeof p !== "object" ||
          p === null ||
          (p.state !== "approval-requested" && p.state !== "approval-responded")
        ) {
          continue;
        }
        const approval = p.approval as { id?: unknown } | undefined;
        if (
          typeof approval?.id === "string" &&
          !autoRejectedIds.current.has(approval.id)
        ) {
          ids.push(approval.id);
        }
      }
    }
    if (ids.length === 0) {
      // The failed send had no approvals to reject. The old behavior
      // silently dropped the error here (nothing surfaced at all);
      // this is exactly the class of failure the dialog is for.
      setFailureNotice({
        kind: "send",
        detail: String(error).slice(0, 300),
        hint: clientFailureHint(String(error))});
      return;
    }
    for (const id of ids) autoRejectedIds.current.add(id);
    const stopped =
      /abort|cancel/i.test(String(error)) || status === "streaming";
    for (const id of ids) {
      void addToolApprovalResponse({
        id,
        approved: false,
        reason: stopped
          ? "System: the run was stopped by the user before completing. " +
            "This rejection is automatic cleanup — you may retry on request."
          : SYSTEM_RETRY_REASON});
    }
    setFailureNotice(
      stopped
        ? {
            kind: "recovery",
            detail:
              "Run stopped — the pending tool approvals were rejected as cleanup.",
            hint: "Send a message to continue."}
        : {
            kind: "send",
            detail: String(error).slice(0, 300),
            hint: "Its pending approvals were auto-rejected so the conversation can continue — ask the model to retry."},
    );
  }, [error, uiMessages, status]);

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


  // A run can outlive this tab (reload, tab switch, second browser) — or
  // start in one while this tab sits idle. While the server reports a
  // run live, this client stays subscribed to it at a tight cadence;
  // when it is not live the watch does NOT stop — it keeps re-asking at
  // a wider cadence, so a run opened in another tab is noticed within
  // one idle poll, and one that started and settled entirely between
  // two polls is still caught: a finished run stays readable for the
  // journal grace window (JOURNAL_GRACE_SECONDS), and its settled
  // status is fingerprinted (boot|generation|outcome|detail). boot is
  // the server process identity — generation restarts with the process,
  // so without boot a fresh process's run #1 could collide with an
  // already-handled run #1 of the previous process and be missed.
  //
  // A settled run is handled exactly once per tab: reload the saved
  // turn, and if it failed open the dialog. The one exception is a
  // settled run that predates this tab's watch of the session — seen on
  // the very first poll, with the tab not following anything — which is
  // adopted silently: a failure that aged in before the tab loaded is
  // history, the transcript already carries the durable ❌ note, and a
  // load must never pop a modal for a run this browser never watched.
  const FOLLOW_POLL_IDLE_MS = 15000;
  const FOLLOW_POLL_LIVE_MS = 3000;
  useEffect(() => {
    if (!sessionId || isStreaming) return;
    // A session switch must not inherit the previous session's watch
    // memory: this tab has not watched anything in the new session yet.
    if (settledRunRef.current && settledRunRef.current.session !== sessionId) {
      settledRunRef.current = null;
      isFollowingRef.current = false;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const watch = async () => {
      if (cancelled) return;
      let sawLive = false;
      try {
        const resp = await fetch(
          `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
        );
        if (cancelled) return;
        if (resp.ok) {
          const status = (await resp.json()) as {
            live?: unknown;
            boot?: unknown;
            generation?: unknown;
            outcome?: unknown;
            detail?: unknown;
            hint?: unknown;
          };
          if (cancelled) return;
          if (status.live === true) {
            // The GET stream replays the run's journal from the
            // start, so the turn rebuilds exactly as it happened.
            // A follow that fails must not strand the page: the run
            // is still live, so the next watch subscribes again.
            isFollowingRef.current = true;
            sawLive = true;
            void sdkResumeStream().catch(() => {
              // A run can end in the instant between the status
              // check and the subscribe. The backend answers that
              // with 204 ("nothing to follow"), which is not an
              // error; anything else is retried by the next watch,
              // and the saved transcript is the fallback either way.
            });
          } else {
            // Not live. Two shapes reach here: plain idle (the run
            // was pruned, or none settled in this server process) or
            // a settled run still inside the journal grace window,
            // which carries an outcome.
            const generation =
              typeof status.generation === "number" ? status.generation : 0;
            const outcome =
              typeof status.outcome === "string" ? status.outcome : null;
            if (generation === 0 && outcome === null) {
              if (isFollowingRef.current) {
                // A followed run whose settled status is gone
                // entirely: a throttled background tab slept
                // through the whole grace window. Reload the
                // transcript it missed.
                isFollowingRef.current = false;
                setPendingSteering([]);
                await reloadSession(sessionId);
              } else if (settledRunRef.current === null) {
                // First look at a session with nothing settled:
                // prime the sentinel so any run that settles
                // while this tab is open is unmistakably new.
                settledRunRef.current = {
                  session: sessionId,
                  fingerprint: ""};
              }
            } else if (outcome !== null) {
              // A run's settled fingerprint.
              const fingerprint = [
                String(status.boot ?? ""),
                String(status.generation ?? ""),
                String(status.outcome ?? ""),
                String(status.detail ?? "").slice(0, 160)].join("|");
              const known = settledRunRef.current;
              if (known === null && !isFollowingRef.current) {
                // The settled run predates this tab's watch of
                // the session — adopt it without acting.
                settledRunRef.current = {
                  session: sessionId,
                  fingerprint};
              } else if (
                known === null ||
                known.session !== sessionId ||
                known.fingerprint !== fingerprint
              ) {
                // A settled run this tab has not accounted for:
                // it either followed it to the end or the whole
                // run happened between two polls. Take the
                // server's saved turn as the transcript of what
                // happened — that turn is also where an unread
                // steer now lives, so the strip empties with
                // the run it belonged to. A failure is reported
                // once, here: the journal's failure text is the
                // record, the dialog is the read-me-once
                // notice, and the hint comes from the server
                // (one hint logic, never copied here).
                if (isFollowingRef.current) {
                  isFollowingRef.current = false;
                  setPendingSteering([]);
                }
                await reloadSession(sessionId);
                if (!cancelled) {
                  settledRunRef.current = {
                    session: sessionId,
                    fingerprint};
                  if (outcome === "failed") {
                    setFailureNotice({
                      kind: "run",
                      detail:
                        typeof status.detail === "string" ? status.detail : "",
                      hint:
                        typeof status.hint === "string" && status.hint
                          ? status.hint
                          : undefined});
                  }
                }
              }
            }
          }
        }
      } catch {
        // Backend unreachable - the next watch retries.
      }
      // Every non-live path (idle, settled, unreadable status) re-arms:
      // the watch is exactly the mechanism that notices a run opened
      // in another tab, and one that stops when no run is live never
      // starts following.
      if (!cancelled) {
        timer = setTimeout(
          () => void watch(),
          sawLive ? FOLLOW_POLL_LIVE_MS : FOLLOW_POLL_IDLE_MS,
        );
      }
    };
    void watch();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, isStreaming, sdkResumeStream, reloadSession]);

  // When a run this client SENT ends, check how it ended. A failed run
  // streams its failure text and then closes the SSE stream "cleanly" -
  // the wire never errors - so the browser's own turn can only learn the
  // outcome from the run's status. Without this check the failure would
  // ride the journal text alone and never open the dialog.
  // Fires on the streaming→idle transition only: an old failure seen on
  // mount never pops a modal for a run this browser never watched.
  const ranHereRef = useRef(false);
  useEffect(() => {
    if (isStreaming) {
      ranHereRef.current = true;
      return;
    }
    if (!ranHereRef.current || !sessionId) return;
    ranHereRef.current = false;
    let cancelled = false;
    void (async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
        );
        if (!resp.ok || cancelled) return;
        const s = (await resp.json()) as {
          outcome?: unknown;
          detail?: unknown;
          hint?: unknown;
        };
        if (cancelled || s.outcome !== "failed") return;
        setFailureNotice({
          kind: "run",
          detail: typeof s.detail === "string" ? s.detail : "",
          hint: typeof s.hint === "string" && s.hint ? s.hint : undefined});
      } catch {
        // Status unreachable - the journal text in the transcript
        // is the durable record; the dialog is the transient notice.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isStreaming, sessionId]);

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
    autoRejectedIds.current.clear();
    void sdkSendMessage({ text });
  };

  // Programmatic send (used by App's slash-command handler).
  // Also clears the input box when the sent content matches it.
  const sendMessage = async (content: string) => {
    if (!content.trim() || isStreaming) return;
    setInput((prev) => (prev.trim() === content.trim() ? "" : prev));
    setFailureNotice(null);
    lastSentTextRef.current = content;
    autoRejectedIds.current.clear();
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
    autoRejectedIds.current.clear();
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
    isFollowingRef.current = false;
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
    editApprovalArgs,
    revertApproval,
    questionBatch,
    respondToQuestion,
    declineAllQuestions,
    failureNotice,
    dismissFailureNotice: () => setFailureNotice(null),
    retryLast,
    sessionId,
    sessionTitle,
    newServerChat,
    openSession};
}
