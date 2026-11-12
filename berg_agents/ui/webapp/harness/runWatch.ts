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
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * The run watch - knowing what a run did, from any tab.
 *
 * A run can outlive this tab (reload, tab switch, second browser) - or
 * start in one while this tab sits idle. This module is how the client
 * keeps up: it samples the server's run status, follows a live run by
 * subscribing to its journal replay, and accounts for a settled run
 * exactly once per tab.
 *
 * The fingerprint is the heart of it: a settled run is identified by
 * boot|generation|outcome|detail. boot is the server process identity -
 * generation restarts with the process, so without boot a fresh
 * process's run #1 could collide with an already-handled run #1 of the
 * previous process and be missed.
 *
 * Two effects, one vocabulary:
 * - the watch: follows live runs, accounts for settled ones, and never
 *   pops a modal for a run this browser never saw (a failure that aged
 *   in before the tab loaded is history - the transcript already carries
 *   the durable ❌ note);
 * - the sent-run check: a run THIS client sent failed in a way the wire
 *   cannot show (a failed run streams its failure text and then closes
 *   the SSE stream cleanly), so the outcome is read once on the
 *   streaming→idle transition.
 */

import { useEffect, useRef } from "react";

/** How often the watch samples a live run (it is following it). */
const FOLLOW_POLL_LIVE_MS = 3000;
/** How often it samples an idle session (it must notice a new run). */
const FOLLOW_POLL_IDLE_MS = 15000;

/** What the hook needs from the chat hook's own render. */
export interface UseRunWatchDeps {
  /** Active session id, or null when none is adopted yet. */
  sessionId: string | null;
  /** Whether a run is streaming right now. */
  isStreaming: boolean;
  /** Base URL of the Berg Agents API. */
  apiBase: string;
  /** Subscribe to a live run's journal (AI SDK resume stream). */
  resumeStream: () => Promise<unknown>;
  /** Reload a session's transcript from the server. */
  reloadSession: (id: string) => Promise<unknown>;
  /** Report a failed run (the failure dialog). */
  setFailureNotice: (notice: {
    kind: "run";
    detail: string;
    hint?: string;
  }) => void;
  /** Clear the steering strip when the run it belonged to ends. */
  setPendingSteering: (texts: string[]) => void;
}

/** What the hook hands back to the chat hook. */
export interface RunWatch {
  /** Drop the follow state: nothing is being followed any more. */
  stopFollowing: () => void;
}

/**
 * Follow and account for the session's runs.
 *
 * @param deps - Session, streaming state, API base and the three
 *     channels back into the chat hook.
 * @returns The one action the chat hook needs: drop the follow state
 *     (an explicit Stop ends the run for good).
 */
export function useRunWatch(deps: UseRunWatchDeps): RunWatch {
  const {
    sessionId,
    isStreaming,
    apiBase,
    resumeStream,
    reloadSession,
    setFailureNotice,
    setPendingSteering} = deps;

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
          `${apiBase}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
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
            void resumeStream().catch(() => {
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
  }, [
    sessionId,
    isStreaming,
    apiBase,
    resumeStream,
    reloadSession,
    setFailureNotice,
    setPendingSteering]);

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
          `${apiBase}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
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
  }, [isStreaming, sessionId, apiBase, setFailureNotice]);

  return {
    stopFollowing: () => {
      isFollowingRef.current = false;
    }};
}
