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
"use client";

import type { PendingQuestion, PendingQuestionAnswer } from "@/harness/askUser";

import * as React from "react";
import { RiCheckLine, RiCloseCircleLine } from "@remixicon/react";

import { Button } from "@/components/ui/button";
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireChoice,
  QuestionnaireChoices,
  QuestionnaireDescription,
  QuestionnaireError,
  QuestionnaireInput,
  QuestionnaireItem,
  QuestionnaireNext,
  QuestionnairePrevious,
  QuestionnaireProgress,
  QuestionnaireSubmit,
  QuestionnaireTitle} from "@/components/ui/questionnaire";

export interface AskUserQuestionnaireProps {
  /** An ask_user_question call containing 1..N questions. */
  question: PendingQuestion;
  /** Locks the form while the agent stream is running. */
  isStreaming: boolean;
  /** Wired directly to respondToQuestion(id, answers, declined). */
  onAnswer: (
    questionId: string,
    answers: PendingQuestionAnswer[],
    declined: boolean,
  ) => void;
}

export function AskUserQuestionnaire({
  question,
  isStreaming,
  onAnswer}: AskUserQuestionnaireProps) {
  // Hooks must always run unconditionally at the top of the component
  const questionnaireItems = React.useMemo(
    () =>
      question.questions.map((q) => ({
        name: q.header,
        required: true,
        multiple: q.multiSelect,
        choices: q.options.map((opt) => ({
          value: opt.label}))})),
    [question.questions],
  );

  // 1. Already answered or declined state
  if (question.answered) {
    return (
      <div className="flex items-center justify-between rounded-lg border bg-muted/40 px-3.5 py-2.5 text-sm">
        <div className="flex items-center gap-2">
          {question.declined ? (
            <>
              <RiCloseCircleLine className="size-4 shrink-0 text-muted-foreground" />
              <span className="text-muted-foreground">
                Questions declined (
                {question.questions.map((q) => q.header).join(", ")})
              </span>
            </>
          ) : (
            <>
              <RiCheckLine className="size-4 shrink-0 text-emerald-600" />
              <span>
                Answer submitted (
                {question.questions.map((q) => q.header).join(", ")})
              </span>
            </>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {isStreaming ? "Resuming..." : "Done"}
        </span>
      </div>
    );
  }

  // 2. Guard against malformed or empty tool calls
  if (question.questions.length === 0) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        Could not parse question data from the tool call.
      </div>
    );
  }

  // 3. Build answers array and send via onAnswer(questionId, answers, false)
  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isStreaming) return;

    const formData = new FormData(event.currentTarget);

    const answers: PendingQuestionAnswer[] = question.questions.map((q) => {
      const knownLabels = new Set(q.options.map((opt) => opt.label));

      if (q.multiSelect) {
        const allValues = formData
          .getAll(q.header)
          .filter(
            (v): v is string => typeof v === "string" && v.trim().length > 0,
          );

        const selected = allValues.filter((v) => knownLabels.has(v));
        const customValues = allValues
          .map((v) => v.trim())
          .filter((v) => v.length > 0 && !knownLabels.has(v));
        const customAnswer =
          customValues.length > 0 ? customValues.join(", ") : undefined;

        return {
          header: q.header,
          selected,
          ...(customAnswer ? { customAnswer } : {})};
      }

      const rawValue = formData.get(q.header);
      const valStr = typeof rawValue === "string" ? rawValue.trim() : "";

      if (knownLabels.has(valStr)) {
        return {
          header: q.header,
          selected: [valStr]};
      }

      return {
        header: q.header,
        selected: [],
        ...(valStr.length > 0 ? { customAnswer: valStr } : {})};
    });

    onAnswer(question.id, answers, false);
  }

  // 4. Decline this entire tool call
  function handleDecline() {
    if (isStreaming) return;
    onAnswer(question.id, [], true);
  }

  return (
    <div className="rounded-lg border bg-card p-4 shadow-xs">
      <Questionnaire
        className="w-full space-y-4"
        items={questionnaireItems}
        onSubmit={handleSubmit}
      >
        {question.questions.length > 1 && <QuestionnaireProgress />}

        {question.questions.map((q) => (
          <QuestionnaireItem
            key={q.header}
            required
            multiple={q.multiSelect}
            name={q.header}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                {q.header}
              </span>
              {q.multiSelect && (
                <span className="text-xs text-muted-foreground">
                  (Select one or more)
                </span>
              )}
            </div>

            <QuestionnaireTitle>{q.question}</QuestionnaireTitle>
            <QuestionnaireDescription>
              {q.multiSelect
                ? "Select all options that apply, or write your own answer below."
                : "Choose an option or enter a custom response."}
            </QuestionnaireDescription>

            <QuestionnaireChoices>
              {q.options.map((opt) => (
                <QuestionnaireChoice key={opt.label} value={opt.label}>
                  <div className="flex flex-col text-left">
                    <span className="font-medium">{opt.label}</span>
                    {opt.description && (
                      <span className="text-xs text-muted-foreground">
                        {opt.description}
                      </span>
                    )}
                  </div>
                </QuestionnaireChoice>
              ))}

              <QuestionnaireInput
                aria-label={`Custom answer for ${q.header}`}
                placeholder="Other (type your own answer)…"
              />
            </QuestionnaireChoices>

            <QuestionnaireError />
          </QuestionnaireItem>
        ))}

        <QuestionnaireActions className="flex flex-wrap items-center justify-between gap-2 pt-2">
          <Button
            isDisabled={isStreaming}
            size="sm"
            type="button"
            variant="ghost"
            onPress={handleDecline}
          >
            Decline
          </Button>

          <div className="flex items-center gap-2">
            {question.questions.length > 1 && (
              <>
                <QuestionnairePrevious size="sm" variant="outline">
                  Previous
                </QuestionnairePrevious>
                <QuestionnaireNext size="sm" variant="outline">
                  Next
                </QuestionnaireNext>
              </>
            )}
            <QuestionnaireSubmit disabled={isStreaming} size="sm">
              Submit answer
            </QuestionnaireSubmit>
          </div>
        </QuestionnaireActions>
      </Questionnaire>
    </div>
  );
}
