import type { DelegationQuestion } from "@/harness";

import { Button } from "@heroui/react";
import { useState } from "react";

import { MAX_DELEGATION_ANSWER_CHARS } from "@/harness/delegationQuestions";

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
export default function DelegationQuestionCard({
    onAnswer,
    question}: {
    question: DelegationQuestion;
    onAnswer: (taskId: string, answer: string) => Promise<boolean>;
}) {
    const [answer, setAnswer] = useState("");
    const [state, setState] = useState<"draft" | "sending" | "sent" | "failed">(
        "draft",
    );

    const trimmed = answer.trim();
    const canSend = trimmed.length > 0 && state !== "sending";

    const submit = async () => {
        if (!canSend) return;
        setState("sending");
        // A false return is not an error to shout about: it means the task
        // is no longer waiting (the run ended, or it was answered from
        // elsewhere). The card keeps its text so the user can see what
        // they tried, and says so plainly.
        const ok = await onAnswer(question.taskId, trimmed);
        setState(ok ? "sent" : "failed");
    };

    return (
        <div className="my-2 rounded-lg border border-default-200 bg-content1 p-3">
            <div className="mb-1 text-sm font-medium">
                {question.agentName} is waiting for your answer
            </div>
            <p className="mb-2 whitespace-pre-wrap text-sm text-default-600">
                {question.question}
            </p>
            <textarea
                className="w-full resize-y rounded-md border border-default-200 bg-transparent p-2 text-sm"
                maxLength={MAX_DELEGATION_ANSWER_CHARS}
                placeholder="Your answer…"
                rows={2}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void submit();
                    }
                }}
            />
            <div className="mt-2 flex items-center gap-2">
                <Button
                    isDisabled={!canSend}
                    size="sm"
                    variant="primary"
                    onPress={() => void submit()}
                >
                    {state === "sending" ? "Sending…" : "Send answer"}
                </Button>
                <span className="text-xs text-default-400">
                    {state === "sent"
                        ? "Sent — the task will continue."
                        : state === "failed"
                          ? "Could not send — the task may have moved on. Check the run is still live."
                          : "Enter sends, Shift+Enter adds a line."}
                </span>
            </div>
        </div>
    );
}
