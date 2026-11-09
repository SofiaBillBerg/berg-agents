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
 * A delegated sub-agent's question: read it off the wire, answer it.
 *
 * When a delegated task calls `ask_parent` it blocks and the harness
 * backgrounds it, and the question reaches this client as a
 * `data-delegation-question` part carrying the task id and the text.
 * That is the ONE place the question exists: the task's own run holds the
 * waiting future, so there is no approval id here to match against and no
 * resume body to build.
 *
 * This is deliberately NOT the ask_user_question batch. That surface
 * answers a deferred tool call on the PARENT run, which has paused; this
 * answers a question a CHILD asked while the parent is still streaming.
 * Same need - the user answers something an agent asked - different
 * lifetime, different id, different endpoint. Two readers here, not one.
 */

import { apiFetch } from "@/envConfig";

/** Chunk type the backend emits for a delegated task's question. */
export const DELEGATION_QUESTION_TYPE = "data-delegation-question";

/** Chunk type the backend emits to bracket a delegated task's stream. */
export const DELEGATION_MARKER_TYPE = "data-subagent";

/** The free-text cap on an answer. The server applies the same limit. */
export const MAX_DELEGATION_ANSWER_CHARS = 2000;

/** One delegated task's question, as the card renders it. */
export interface DelegationQuestion {
    /** The waiting task's id - pass back to answerDelegatedQuestion. */
    taskId: string;
    /** Which sub-agent is waiting (for the card's byline). */
    agentName: string;
    /** The question text, verbatim. */
    question: string;
}

/**
 * Read the delegated questions a set of messages carries.
 *
 * Only the LAST assistant message can hold a live question: a question
 * that outlived its turn leaves its part behind, but the task it belonged
 * to has settled, so the card would answer into nothing. The 409 the
 * endpoint returns is the honest backstop, and this scan just avoids
 * drawing a card that is already dead.
 *
 * @param messages - The raw UI messages.
 * @returns The live questions, in the order they were asked.
 */
export function delegationQuestionsFrom(
  messages: readonly unknown[],
): DelegationQuestion[] {
  const found: DelegationQuestion[] = [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as Record<string, unknown> | undefined;
    if (!msg || msg.role !== "assistant") continue;
    const parts = msg.parts;
    if (!Array.isArray(parts)) continue;
    for (const part of parts) {
      const p = part as Record<string, unknown>;
      if (p?.type !== DELEGATION_QUESTION_TYPE) continue;
      const data = p.data as Record<string, unknown> | undefined;
      const taskId = typeof data?.taskId === "string" ? data.taskId : null;
      if (!taskId) continue;
      if (found.some((q) => q.taskId === taskId)) continue;
      found.push({
        taskId,
        agentName:
          typeof data?.agentName === "string" && data.agentName
            ? data.agentName
            : "the sub-agent",
        question:
          typeof data?.question === "string" ? data.question : ""});
    }
    // Only the last assistant message carries the live batch.
    break;
  }
  return found;
}

/**
 * Answer a delegated task's question.
 *
 * The parent run is live and streaming while the task waits, so this is
 * its own request rather than part of a resume body (a resume would be
 * read as steering). A 409 means the card is stale - the run ended, or
 * the task was answered from elsewhere - and the caller should expire
 * the card rather than show a failure.
 *
 * @param sessionId - Session whose run holds the task.
 * @param taskId - The waiting task's id.
 * @param answer - The user's answer, verbatim.
 * @returns True when the answer reached a waiting task.
 */
export async function answerDelegatedQuestion(
  sessionId: string,
  taskId: string,
  answer: string,
): Promise<boolean> {
  try {
    const resp = await apiFetch(
      `/api/chat/delegation-answer?session=${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId, answer })},
    );
    return resp.ok;
  } catch {
    // Backend unreachable: the card stays, the user can retry.
    return false;
  }
}

/** One delegated task the UI can steer or stop, and whether it is live. */
export interface LiveDelegatedTask {
    /** The task's id, from the opening bracket. */
    taskId: string;
    /** Which sub-agent is running it, for the control's label. */
    agentName: string;
}

/**
 * Read the delegated tasks that are still live, from a message's parts.
 *
 * A task is live between its bracket's start (which carries the id) and
 * its end. Only the last assistant message is read, for the same reason
 * the question batch is: a bracket left open by a turn that ended is not
 * a task anyone can still steer, and the endpoints say so with a 409.
 *
 * @param messages - The raw UI messages.
 * @returns The live tasks, in the order they were started.
 */
export function liveDelegatedTasksFrom(
  messages: readonly unknown[],
): LiveDelegatedTask[] {
  const open = new Map<string, LiveDelegatedTask>();
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as Record<string, unknown> | undefined;
    if (!msg || msg.role !== "assistant") continue;
    const parts = msg.parts;
    if (!Array.isArray(parts)) continue;
    for (const part of parts) {
      const p = part as Record<string, unknown>;
      if (p?.type !== DELEGATION_MARKER_TYPE) continue;
      const data = p.data as Record<string, unknown> | undefined;
      const phase = data?.phase;
      const taskId = typeof data?.taskId === "string" ? data.taskId : "";
      if (phase === "start" && taskId) {
        open.set(taskId, {
          taskId,
          agentName:
            typeof data?.agentName === "string" && data.agentName
              ? data.agentName
              : "the sub-agent"});
      } else if (phase === "end" && taskId) {
        open.delete(taskId);
      }
    }
    break;
  }
  return [...open.values()];
}

/**
 * Steer a running delegated task with a message from the user.
 *
 * The child reads it at its next model request, which is the harness's
 * own contract: a message cannot interrupt a step already in flight.
 *
 * @param sessionId - Session whose run holds the task.
 * @param taskId - The task to steer.
 * @param message - What to tell it.
 * @returns True when the task was running and took the message.
 */
export async function messageDelegatedTask(
  sessionId: string,
  taskId: string,
  message: string,
): Promise<boolean> {
  try {
    const resp = await apiFetch(
      `/api/chat/delegation-message?session=${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId, message })},
    );
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Stop a running delegated task.
 *
 * @param sessionId - Session whose run holds the task.
 * @param taskId - The task to stop.
 * @param force - Interrupt the current step instead of letting it finish.
 * @returns True when a task was running and the stop was applied.
 */
export async function cancelDelegatedTask(
  sessionId: string,
  taskId: string,
  force = false,
): Promise<boolean> {
  try {
    const resp = await apiFetch(
      `/api/chat/delegation-cancel?session=${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ taskId, force })},
    );
    return resp.ok;
  } catch {
    return false;
  }
}
