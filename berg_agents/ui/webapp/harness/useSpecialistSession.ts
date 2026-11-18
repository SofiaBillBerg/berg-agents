import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useCallback, useEffect, useRef, useState } from "react";

import { toChatMessage } from "@/harness/messageParts";

/** What a specialist is doing, in the terms its session surface acts on. */
export type SpecialistSessionState = "pending" | "working" | "waiting" | "done";

/** One call a waiting specialist needs answered. */
export interface PendingCall {
  tool_call_id: string;
  tool_name: string;
  args: unknown;
}

/** One specialist session: its stream, its gates, and the actions on it. */
export interface SpecialistSession {
  /** The run id this session is addressing — the handle for every action. */
  runId: string;
  /** What the specialist has said and done so far, in the chat's own shape. */
  transcript: ReturnType<typeof toChatMessage>[];
  /** What the run is doing right now. */
  state: SpecialistSessionState;
  /** The calls it is waiting on, when it is waiting. */
  pending: PendingCall[];
  /** True while the run is live. */
  live: boolean;
  /** Answer one of its pending calls. */
  answer: (call: PendingCall, approved: boolean, reason?: string) => void;
  /** Send it an instruction mid-run. */
  steer: (text: string) => void;
  /** Stop it. */
  stop: (reason?: string) => void;
  /** Any error the last action produced. */
  error: string | null;
}

/**
 * One specialist's session, as a place to be.
 *
 * The specialist is a run of its own in berg's Python backend — durable, with its
 * own gates and its own stream. This hook makes that run a *session*: its stream
 * feeds the same SDK accumulator (and so the same `ChatTranscript`) the chat page
 * uses, its pending calls surface as gates you can answer from here, and
 * steering and stop reach it directly.
 *
 * Nothing here is a second protocol. The stream is berg's own SSE
 * (`encode_run_stream` — the Vercel AI frames the chat page already renders), so
 * the reading path is the SDK's own resume: point `useChat` at this run's stream,
 * and it replays and tails it. The actions are the same three routes the
 * orchestrator's tools call, reached from here instead of through it.
 *
 * @param runId - The run whose session this is.
 * @returns The session: transcript, state, gates, and the actions on it.
 */
export function useSpecialistSession(runId: string): SpecialistSession {
  const [state, setState] = useState<SpecialistSessionState>("pending");
  const [pending, setPending] = useState<PendingCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  // The run is live until it says otherwise; polling only runs while it is.
  const [live, setLive] = useState(true);

  /*eslint @typescript-eslint/no-unused-vars: "off"*/
  const { messages, resumeStream, status } = useChat({
    // The run's id IS the session's id: the SDK addresses a reconnect by
    // chat id, and a run id is what identifies this specialist's turn.
    id: runId,
    transport: new DefaultChatTransport({
      api: "/api/workflow/chat",
      // Reading is a plain GET of the run's own stream — the durable
      // journal, not a re-send. Named rather than derived, because under
      // /api/* a dynamic segment is claimed by the proxy rewrite before
      // its handler runs, so the URL has to be spelled out.
      prepareReconnectToStreamRequest: ({ id }) => ({
        api: `/api/workflow/chat/${id}/stream`})})});

  // Adopt the run's stream on mount. This is the SDK's own resume path: the
  // run's frames are replayed and tailed, and the same accumulator the chat
  // uses folds them into messages — so what is rendered here is the recorded
  // turn, not a reconstruction of it.
  const adopted = useRef<string | null>(null);
  useEffect(() => {
    if (adopted.current === runId) return;
    adopted.current = runId;
    void resumeStream();
  }, [runId, resumeStream]);

  // The run's state and what it is waiting on, polled while it is live. The
  // stream says what the specialist DID; this says what it NEEDS, which is
  // the half that has to reach the user as a gate rather than as a frame.
  useEffect(() => {
    if (!live) return;
    let alive = true;
    const poll = async (): Promise<void> => {
      try {
        const response = await fetch(
          `/api/workflow/chat/${encodeURIComponent(runId)}/state`,
        );
        if (!response.ok) return;
        const data = (await response.json()) as {
          state?: SpecialistSessionState;
          pending?: PendingCall[];
        };
        if (!alive) return;
        setState(data.state ?? "pending");
        setPending(Array.isArray(data.pending) ? data.pending : []);
        setLive(data.state === "pending" || data.state === "working");
      } catch {
        // A failed poll leaves the previous state standing: the stream
        // below still renders what the specialist has done, so a
        // transient failure must not blank the session.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [runId, live]);

  /**
   * POST one of the run's routes, with its error surfaced rather than thrown.
   *
   * @param path - The route, relative to the backend.
   * @param body - The JSON body.
   */
  const post = useCallback(
    async (path: string, body: unknown): Promise<void> => {
      setError(null);
      try {
        const response = await fetch(
          `/api/workflow/chat/${encodeURIComponent(runId)}/${path}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)},
        );
        if (!response.ok) {
          const detail = await response.text();
          setError(`${path} -> ${response.status} ${detail.slice(0, 200)}`);
          return;
        }
        // A `write` or a steer changes what the run is waiting on, so the
        // next poll should see the new shape immediately.
        if (path === "approval" || path === "steer") setLive(true);

        // An answer does not resume THIS run — it ends it and starts the
        // next one carrying the decision (berg's durable gate: the pass
        // has already ended, so a decision arrives as a new run). The
        // session therefore follows its own continuation, and the URL
        // keeps naming the run currently being addressed rather than the
        // parked one whose gate just cleared.
        if (path === "approval") {
          const raw = await response.text();
          try {
            const resumed = JSON.parse(raw) as { run_id?: string };
            if (resumed.run_id && resumed.run_id !== runId) {
              window.location.assign(
                `/specialist/${encodeURIComponent(resumed.run_id)}`,
              );
            }
          } catch {
            // No JSON body: the session stays where it is and the
            // next poll reports what changed.
          }
        }
      } catch (err) {
        setError(`${path} failed: ${String(err)}`);
      }
    },
    [runId],
  );

  const answer = useCallback(
    (call: PendingCall, approved: boolean, reason?: string): void => {
      void post("approval", {
        decision: approved ? "approved" : "rejected",
        reason});
    },
    [post],
  );

  const steer = useCallback(
    (text: string): void => {
      void post("steer", { text });
    },
    [post],
  );

  const stop = useCallback(
    (reason?: string): void => {
      void post("stop", { reason });
    },
    [post],
  );

  return {
    runId,
    transcript: messages.map((message: UIMessage) => toChatMessage(message)),
    state,
    pending,
    live,
    answer,
    steer,
    stop,
    error};
}
