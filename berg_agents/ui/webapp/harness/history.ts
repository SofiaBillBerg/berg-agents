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
 * History hygiene - what the client may echo back, and what it must not.
 *
 * Every send and every restore passes through here. The rules are
 * about single-use state: an approval answer and a question answer
 * are per-run nonces, and replaying one against a run that no longer
 * exists is what turns a stale card into a cryptic backend failure.
 * Split out of the chat hook because the transport
 * (prepareSendMessagesRequest) and the restore path both call it, and
 * because it is the one place where a future edit can silently
 * resurrect a blocking approval on reload. Moved byte-identical.
 */

import {ASK_USER_TOOL_NAME, isQuestionAnswerPayload} from "./askUser";
import {partToolName} from "./messageParts";


/**
 * Sanitize a restored conversation so stale single-use state can never
 * poison a fresh run. Approval responses are per-run nonces: replaying
 * an old `approval-responded` part makes the backend try to resume a
 * dead run (observed as cryptic failures). Parts answered but never
 * executed revert to `approval-requested` so the user is asked again;
 * malformed parts are dropped. A question answer payload sitting in an
 * earlier message is the same nonce problem in a different shape, so it
 * is expired to an honest sentence (only the live last message may
 * carry answers to the backend).
 *
 * Restores (`preserveLatest === false`) go further: the backend is
 * stateless, so EVERY restored approval id belongs to a dead run.
 * Their ids are stripped, which renders them as expired and makes
 * them unanswerable — a reload can never resurrect a blocking
 * approval card again.
 */
export function sanitizeHistory(msgs: unknown[], preserveLatest: boolean): unknown[] {
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
        parts: (m.parts as unknown[]).flatMap((p) => {
          if (typeof p !== "object" || p === null) return [];
          const part = p as {
            type?: unknown;
            state?: unknown;
            approval?: unknown;
          };
          // Malformed parts can never resume — drop them.
          if (typeof part.type !== "string") return [];
          const isTool =
            part.type === "dynamic-tool" || part.type.startsWith("tool-");
          // Non-restore: the client never owns the system prompt
          // (the backend builds it), so replayed system parts from a
          // restored session are what triggers its strip warning.
          if (!preserveLatest && (m as { role?: unknown }).role === "system") {
            return [];
          }
          if (
            isTool &&
            part.state === "approval-responded" &&
            (part as { output?: unknown }).output === undefined
          ) {
            // Answered but never executed: re-ask instead of replaying.
            // `approval` must stay a real object AND carry an `id`:
            // the AI SDK's addToolApprovalResponse reads
            // `part.approval.id` with no optional chaining, so both
            // an undefined approval and a missing id leave an
            // unanswerable card that throws on the next click.
            // Without an id there is nothing to ask again, so the
            // part expires like any other dead-run approval.
            const previous =
              typeof part.approval === "object" && part.approval !== null
                ? (part.approval as { id?: unknown })
                : undefined;
            const approvalId =
              typeof previous?.id === "string" ? previous.id : undefined;
            if (!approvalId) {
              const { approval: _dropped, ...rest } = part as Record<
                string,
                unknown
              >;
              return [{ ...rest, state: "output-denied" }];
            }
            return [
              {
                ...part,
                state: "approval-requested",
                approval: {
                  ...previous,
                  id: approvalId,
                  approved: undefined,
                  reason: undefined}}];
          }
          if (
            !preserveLatest &&
            isTool &&
            part.state === "approval-requested"
          ) {
            // Dead run (see docstring): expire instead of replaying.
            //
            // The state MUST leave "approval-requested" here. The
            // AI SDK's addToolApprovalResponse filters with
            // `state === "approval-requested" && part.approval.id`
            // and does not guard `approval`, so a requested part
            // with the approval object stripped throws on the next
            // approve click and wedges the run. "output-denied" is
            // the SDK's terminal state for a call that never got
            // approval, and it keeps `approval` absent on purpose.
            const { approval: _dropped, ...rest } = part as Record<
              string,
              unknown
            >;
            return [{ ...rest, state: "output-denied" }];
          }
          if (
            isTool &&
            part.state === "output-available" &&
            partToolName(part as unknown as Record<string, unknown>) ===
              ASK_USER_TOOL_NAME &&
            isQuestionAnswerPayload((part as { output?: unknown }).output)
          ) {
            // A raw answer payload in an EARLIER message belongs
            // to a dead run - only the live last message may
            // carry answers. Left in place, the backend's
            // resume detection would misread the next send as
            // an answer to a run that no longer exists, so the
            // payload is expired to an honest sentence (the
            // model never saw this answer). This runs for every
            // flatMap'd message in both modes: sends strip all
            // but the preserved latest, restores strip all of
            // them (a paused restore preserves its last message
            // whole, above).
            return [
              {
                ...part,
                output:
                  "The run ended before this answer was " +
                  "applied; the question went unanswered."}];
          }
          return [{ ...part }];
        })};
    });
}

/**
 * Reason used for system-initiated rejections (failed sends, see the
 * error effect below). Deliberately retry-friendly: unlike an
 * explicit user rejection, a dead run says nothing about the action
 * itself, so the model should feel free to try again.
 */
export const SYSTEM_RETRY_REASON =
  "System: the previous tool run failed before completing " +
  "(mismatched or interrupted approval state). This rejection is " +
  "automatic cleanup, NOT a human decision — you may retry the same " +
  "action with corrected arguments.";
