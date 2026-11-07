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
 * Failed-send recovery - and the one failure surface that reports it.
 *
 * The backend is stateless, so any approval parts pending when a send
 * errors belong to a run that can never resume: replaying them only
 * reproduces the mismatch error forever. Recovery therefore auto-rejects
 * those pending approvals with the retry-friendly system reason (NOT the
 * firm user-rejection text), tells the user visibly, and lets
 * sendAutomaticallyWhen resume so the model may retry.
 *
 * The loop needs two guards, and both are load-bearing:
 * - already-handled ids are never touched twice, so a persistently
 *   failing backend cannot loop sends forever;
 * - each auto-reject mints NEW approval ids, so an id set can never bound
 *   the loop itself. One failed recovery round disarms it and the next
 *   step needs a human send (observed without it: ~100 messages in
 *   seconds).
 *
 * The failure notice is transient UI on top of the durable record: the
 * journal text in the transcript is what survives (and reloads); the
 * dialog asks to be read once. Recovery actions the system took ride in
 * the notice too, so there is exactly one failure surface.
 */

import type {UIMessage} from "ai";

import {useEffect, useRef, useState} from "react";

import {SYSTEM_RETRY_REASON} from "./history";
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

/** What the hook needs from the chat hook's own render. */
export interface UseSendRecoveryDeps {
    /** The SDK's error for the last send, or null. */
    error: unknown;
    /** The messages as the user currently sees them. */
    uiMessages: readonly UIMessage[];
    /** The SDK's streaming status. */
    status: string;
    /** Mark one approval decided (AI SDK) - the auto-reject channel. */
    addToolApprovalResponse: (response: {
        id: string;
        approved: boolean;
        reason?: string;
    }) => Promise<unknown> | unknown;
}

/** The failure surface and the reset a new send performs. */
export interface SendRecovery {
    /** The active failure notice, or null. */
    failureNotice: FailureNotice | null;
    /** Set the notice (the chat hook clears it on a manual send). */
    setFailureNotice: (notice: FailureNotice | null) => void;
    /** Forget which ids were auto-rejected: the user is driving again. */
    resetRecovery: () => void;
}

/**
 * Own failed-send recovery and the failure dialog's contents.
 *
 * @param deps - The SDK's error/messages/status and the reject channel.
 * @returns The notice, its setter, and the reset a new send performs.
 */
export function useSendRecovery(deps: UseSendRecoveryDeps): SendRecovery {
    const {error, uiMessages, status, addToolApprovalResponse} = deps;

    const [failureNotice, setFailureNotice] = useState<FailureNotice | null>(
        null,
    );
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
    }, [error, uiMessages, status, addToolApprovalResponse]);

    return {
        failureNotice,
        setFailureNotice,
        resetRecovery: () => autoRejectedIds.current.clear()};
}
