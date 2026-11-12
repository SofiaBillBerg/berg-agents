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
 * ask_user_question - the tool's wire identity and its pure decoders.
 *
 * A question pauses the run exactly like an approval does, and every
 * card, marker and resume rule branches on this name to keep the two
 * HITL surfaces separate. The name and the payload decoders live apart
 * from the hook so both the message walker (markers) and the resume
 * rule (sendAutomaticallyWhen) read one definition instead of each
 * keeping its own copy of the strings.
 */

/** The wire tool name of the harness's ask-user call. */
export const ASK_USER_TOOL_NAME = "ask_user_question";

/** One offered choice, kept verbatim - the answer is keyed by label. */
export interface PendingQuestionOption {
  label: string;
  /** What choosing this option means, when the model provided it. */
  description?: string;
}

/** One question as the model declared it, normalized for the card. */
export interface PendingQuestionData {
  /** Short label naming the question; the answer is keyed by it. */
  header: string;
  /** The full question text. */
  question: string;
  /** Whether the user may pick more than one option. */
  multiSelect: boolean;
  options: PendingQuestionOption[];
}

/** One answer inside a submitted response (wire keys are snake_case). */
export interface PendingQuestionAnswer {
  header: string;
  selected: string[];
  customAnswer?: string;
}

/** One ask_user_question call the user still has to answer. */
export interface PendingQuestion {
  /** Tool call id - pass back to respondToQuestion. */
  id: string;
  /** The call's questions, parsed from its args; empty when unreadable. */
  questions: PendingQuestionData[];
  /** True once an answer payload is written (badge until the resume
        fires and the server overwrites the output with the result). */
  answered: boolean;
  /** True when the written payload declines the questions. */
  declined: boolean;
}

/**
 * Whether a part's output is a canonical question-answer payload - the
 * `{answers: [{header, ...}], cancelled}` shape respondToQuestion writes
 * and the server's adapter expects. Once the resume lands, the server
 * overwrites the output with the RENDERED result (`{header: [labels]}` or
 * the DECLINED sentence), which never matches this shape - so spent
 * answers cannot re-arm a resume and completed turns stay completed.
 *
 * @param output - The tool part's `output` field.
 * @returns True when the output is an answer payload awaiting its resume.
 */
export function isQuestionAnswerPayload(output: unknown): boolean {
  if (typeof output !== "object" || output === null) return false;
  const o = output as Record<string, unknown>;
  if (typeof o.cancelled !== "boolean") return false;
  if (!Array.isArray(o.answers)) return false;
  return o.answers.every(
    (entry) =>
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as Record<string, unknown>).header === "string",
  );
}

/**
 * Parse one ask_user_question call's questions from its input args
 * (`{questions: [{header, question, multi_select, options}]}`). The
 * harness validates the same shape before the model's call is accepted,
 * so anything malformed here is a dead-run ghost: it renders as a raw
 * call, never as an answerable card.
 *
 * @param input - The tool call's `input` field.
 * @returns Normalized questions, or an empty array when unreadable.
 */
export function parseQuestionCall(input: unknown): PendingQuestionData[] {
  if (typeof input !== "object" || input === null) return [];
  if (!Array.isArray((input as Record<string, unknown>).questions)) {
    return [];
  }
  const out: PendingQuestionData[] = [];
  for (const raw of (input as Record<string, unknown>).questions as unknown[]) {
    if (typeof raw !== "object" || raw === null) return [];
    const q = raw as Record<string, unknown>;
    if (typeof q.header !== "string" || typeof q.question !== "string") {
      return [];
    }
    if (!Array.isArray(q.options)) return [];
    const options: PendingQuestionOption[] = [];
    for (const opt of q.options) {
      if (typeof opt !== "object" || opt === null) return [];
      const o = opt as Record<string, unknown>;
      if (typeof o.label !== "string") return [];
      options.push({
        label: o.label,
        description:
          typeof o.description === "string" ? o.description : undefined});
    }
    out.push({
      header: q.header,
      question: q.question,
      multiSelect: q.multi_select === true,
      options});
  }
  return out;
}
