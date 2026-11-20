/**
 * One delegated sub-agent's question, answerable in place.
 *
 * The card reads as the sub-agent asking: this is the delegated task's
 * own question, not a permission gate, so nothing here may look like an
 * approval prompt. The wording is "the sub-agent is waiting" rather than
 * "approve", because that is what is actually true - the task is blocked
 * on an answer and nothing else is at stake.
 *
 * There is no `isStreaming` guard, unlike the ask_user card: the parent
 * run is *expected* to still be streaming. The whole shape of this
 * surface is a task that paused inside a live turn, so treating streaming
 * as a reason to refuse the answer would make the card unusable exactly
 * when it matters.
 *
 * Unlike the ask_user card there are no offered options either: a
 * delegated task asks because it cannot reasonably continue, which is a
 * free-text question by nature. So one textarea and one send, capped at
 * the same limit the server enforces.
 */
import type { DelegationQuestion } from "@/harness";

import * as React from "react";

import { MAX_DELEGATION_ANSWER_CHARS } from "@/harness/delegationQuestions";
import { Textarea } from "@/components/ui/textarea";
import {
  Questionnaire,
  QuestionnaireActions,
  QuestionnaireDescription,
  QuestionnaireError,
  QuestionnaireItem,
  QuestionnaireSubmit,
  QuestionnaireTitle} from "@/components/ui/questionnaire";

/**
 * One delegated sub-agent's question, answerable in place.
 *
 * The card reads as the sub-agent asking: this is the delegated task's
 * own question, not a permission gate, so nothing here may look like an
 * approval prompt. The wording is "the sub-agent is waiting" rather than
 * "approve", because that is what is actually true — the task is blocked
 * on an answer and nothing else is at stake.
 *
 * There is no `isStreaming` guard, unlike the ask_user card: the parent
 * run is *expected* to still be streaming.
 */
export default function DelegationQuestionCard({
  onAnswer,
  question}: {
  question: DelegationQuestion;
  onAnswer: (taskId: string, answer: string) => Promise<boolean>;
}) {
  const [answer, setAnswer] = React.useState("");
  const [state, setState] = React.useState<
    "draft" | "sending" | "sent" | "failed"
  >("draft");

  const trimmed = answer.trim();
  const canSend = trimmed.length > 0 && state !== "sending" && state !== "sent";

  const items = React.useMemo(
    () => [
      {
        name: "delegationAnswer",
        required: true}],
    [],
  );

  const submit = async () => {
    if (!canSend) return;
    setState("sending");
    // A false return means the task is no longer waiting (the run ended,
    // or it was answered from elsewhere). Keep the text visible and say so plainly.
    const ok = await onAnswer(question.taskId, trimmed);
    setState(ok ? "sent" : "failed");
  };

  function handleFormSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  return (
    <div className="my-2 rounded-lg border bg-card p-3.5 shadow-xs">
      <Questionnaire
        className="w-full space-y-3"
        items={items}
        onSubmit={handleFormSubmit}
      >
        <QuestionnaireItem required name="delegationAnswer">
          <QuestionnaireTitle className="text-sm font-medium">
            {question.agentName} is waiting for your answer
          </QuestionnaireTitle>
          <QuestionnaireDescription className="whitespace-pre-wrap text-sm text-muted-foreground">
            {question.question}
          </QuestionnaireDescription>

          <Textarea
            aria-label={`Answer for ${question.agentName}`}
            className="mt-2 min-h-[64px] resize-y text-sm"
            disabled={state === "sending" || state === "sent"}
            maxLength={MAX_DELEGATION_ANSWER_CHARS}
            name="delegationAnswer"
            placeholder="Your answer…"
            rows={2}
            value={answer}
            onChange={(e) => {
              setAnswer(e.target.value);
              if (state === "failed") setState("draft");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
          />

          <QuestionnaireError />
        </QuestionnaireItem>

        <QuestionnaireActions className="flex flex-wrap items-center gap-2 pt-1">
          <QuestionnaireSubmit disabled={!canSend} size="sm">
            {state === "sending" ? "Sending…" : "Send answer"}
          </QuestionnaireSubmit>

          <span className="text-xs text-muted-foreground">
            {state === "sent"
              ? "Sent — the task will continue."
              : state === "failed"
                ? "Could not send — the task may have moved on. Check the run is still live."
                : "Enter sends, Shift+Enter adds a line."}
          </span>
        </QuestionnaireActions>
      </Questionnaire>
    </div>
  );
}
