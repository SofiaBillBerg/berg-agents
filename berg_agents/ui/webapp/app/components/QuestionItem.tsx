import type { PendingQuestion, PendingQuestionAnswer } from "@/harness";

import { useState } from "react";
import { Button } from "@heroui/react";

/**
 * The custom-answer cap. The server enforces the same limit when it
 * parses the payload (truncating a forged body); this keeps the honest
 * client from ever writing past it.
 */
const MAX_CUSTOM_ANSWER_CHARS = 2000;

/**
 * One ask_user_question call inside the question batch. One call can
 * carry several questions; all of them are answered together (one tool
 * result). Each question takes either offered option(s) - radio for
 * single-select, checkbox for multi-select - or a custom answer, never
 * both at once (the server's check_response rejects that mix).
 *
 * The card reads as the model asking: these are the agent's own
 * questions, not a system gate, so nothing here may look like a
 * permission prompt.
 */
export function QuestionItem({
  question,
  isStreaming,
  onAnswer}: {
  question: PendingQuestion;
  isStreaming: boolean;
  onAnswer: (
    id: string,
    answers: PendingQuestionAnswer[],
    declined: boolean,
  ) => void;
}) {
  // Drafts, keyed per question header (headers are unique within a call
  // - the harness enforces that before the question ever reaches us).
  const [selected, setSelected] = useState<Record<string, string[]>>(() => {
    const initial: Record<string, string[]> = {};
    for (const q of question.questions) initial[q.header] = [];
    return initial;
  });
  const [customs, setCustoms] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const q of question.questions) initial[q.header] = "";
    return initial;
  });

  // A question is answered once it has either picked option(s) or a
  // nonblank custom answer - and never both (the mix is invalid).
  const validAnswer = (header: string): boolean => {
    const picked = selected[header] ?? [];
    const custom = (customs[header] ?? "").trim();
    if (picked.length > 0) return custom === "";
    return custom.length > 0;
  };
  const allAnswered =
    question.questions.length > 0 &&
    question.questions.every((q) => validAnswer(q.header));

  // Picking an option clears that question's custom answer and vice
  // versa, so the draft can never hold the combination the server
  // would reject.
  const toggleOption = (header: string, label: string, multi: boolean) => {
    setSelected((prev) => {
      const current = prev[header] ?? [];
      if (multi) {
        return {
          ...prev,
          [header]: current.includes(label)
            ? current.filter((l) => l !== label)
            : [...current, label]};
      }
      // Single-select radio: clicking the picked option again clears it.
      return { ...prev, [header]: current.includes(label) ? [] : [label] };
    });
    setCustoms((prev) => ({ ...prev, [header]: "" }));
  };
  const setCustom = (header: string, value: string) => {
    setCustoms((prev) => ({ ...prev, [header]: value }));
    if (value.trim() !== "") {
      setSelected((prev) => ({ ...prev, [header]: [] }));
    }
  };

  const submit = () => {
    if (!allAnswered) return;
    onAnswer(
      question.id,
      question.questions.map((q) => {
        const custom = (customs[q.header] ?? "").trim();
        return custom !== ""
          ? { header: q.header, selected: [], customAnswer: custom }
          : { header: q.header, selected: selected[q.header] ?? [] };
      }),
      false,
    );
  };

  // Answered calls stay in the batch with a badge until the resume
  // fires and the server overwrites their outputs with the results.
  if (question.answered) {
    return (
      <div className="flex flex-col gap-1.5 rounded-md border border-border p-1.5">
        <div className="font-mono text-sm">
          ❓{" "}
          {question.questions.length > 0
            ? question.questions.map((q) => q.header).join(", ")
            : question.id}{" "}
          {question.declined ? (
            <span className="text-xs">🚫 Declined</span>
          ) : (
            <span className="text-xs">✅ Answered</span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-1.5">
      {question.questions.length === 0 ? (
        <div className="text-xs text-muted-foreground">
          ❓ The model asked something its call did not spell out (call{" "}
          {question.id}). Decline to let it continue without an answer.
        </div>
      ) : (
        question.questions.map((q) => (
          <div key={q.header} className="flex flex-col gap-1">
            <div className="text-sm font-medium">{q.question}</div>
            <div className="flex flex-col gap-0.5">
              {q.options.map((opt) => {
                const checked = (selected[q.header] ?? []).includes(opt.label);
                const inputId = `${question.id}-${q.header}-${opt.label}`;
                return (
                  <label
                    key={opt.label}
                    className="hover:bg-surface-soft flex cursor-pointer items-start gap-2 rounded px-1 py-0.5"
                    htmlFor={inputId}
                  >
                    <input
                      checked={checked}
                      className="mt-1"
                      id={inputId}
                      name={
                        q.multiSelect
                          ? undefined
                          : `${question.id}-${q.header}`
                      }
                      type={q.multiSelect ? "checkbox" : "radio"}
                      onChange={() =>
                        toggleOption(q.header, opt.label, q.multiSelect)
                      }
                    />
                    <span className="flex flex-col">
                      <span className="text-sm">{opt.label}</span>
                      {opt.description && (
                        <span className="text-muted-foreground text-xs">
                          {opt.description}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
            <textarea
              aria-label={`Custom answer for ${q.header}`}
              className="bg-surface-soft min-h-12 w-full rounded p-2 text-xs"
              maxLength={MAX_CUSTOM_ANSWER_CHARS}
              placeholder="Or write your own answer…"
              value={customs[q.header] ?? ""}
              onChange={(e) => setCustom(q.header, e.target.value)}
            />
            <div className="text-muted-foreground text-right text-[10px]">
              {(customs[q.header] ?? "").length}/{MAX_CUSTOM_ANSWER_CHARS}
            </div>
          </div>
        ))
      )}
      <div className="flex gap-2">
        <Button
          isDisabled={isStreaming || !allAnswered}
          size="sm"
          variant="primary"
          onPress={submit}
        >
          ✅ Submit answers
        </Button>
        <Button
          isDisabled={isStreaming}
          size="sm"
          variant="secondary"
          onPress={() => onAnswer(question.id, [], true)}
        >
          🚫 Decline
        </Button>
      </div>
    </div>
  );
}

export default QuestionItem;
