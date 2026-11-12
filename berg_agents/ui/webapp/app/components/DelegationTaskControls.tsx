import type { LiveDelegatedTask } from "@/harness";

import { Button } from "@heroui/react";
import { useState } from "react";

import { readStoredSessionId } from "@/harness/sessionIdentity";
import {
  cancelDelegatedTask,
  messageDelegatedTask} from "@/harness/delegationQuestions";

/**
 * Steering and stopping a delegated task that is still running.
 *
 * Rendered inside the delegated task's own card, next to the work it is
 * doing, because that is where the user is looking when they decide to
 * intervene. Two verbs, deliberately different in weight:
 *
 * - **Steer** sends a message the task reads at its next model request.
 *   It cannot interrupt a step already in flight - that is the harness's
 *   own contract - so the copy says "at its next step", not "now".
 * - **Stop** ends the task. It is a two-press affordance: the first
 *   press asks, the second confirms, because a stop tears the task out of
 *   a plan it may be halfway through.
 *
 * Neither control is a permission prompt. The task is the user's own
 * delegated work, and steering it is not approving anything - so nothing
 * here may look like the HITL cards.
 */
export default function DelegationTaskControls({
  onSteered,
  task}: {
  task: LiveDelegatedTask;
  onSteered?: (message: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">(
    "idle",
  );
  const [confirmingStop, setConfirmingStop] = useState(false);

  const sessionId = readStoredSessionId();
  const canSteer = message.trim().length > 0 && state !== "sending";

  const steer = async () => {
    if (!canSteer || !sessionId) return;
    setState("sending");
    const ok = await messageDelegatedTask(
      sessionId,
      task.taskId,
      message.trim(),
    );
    if (ok) {
      setState("sent");
      setMessage("");
      onSteered?.(message.trim());
    } else {
      setState("failed");
    }
  };

  const stop = async (force: boolean) => {
    if (!sessionId) return;
    setConfirmingStop(false);
    await cancelDelegatedTask(sessionId, task.taskId, force);
  };

  return (
    <div className="mt-1 flex flex-col gap-1.5 rounded-md border border-default-200 p-2">
      <div className="flex items-center gap-2">
        <input
          aria-label={`Send a message to ${task.agentName}`}
          className="flex-1 rounded-md border border-default-200 bg-transparent px-2 py-1 text-xs"
          placeholder={`Tell ${task.agentName} what to do…`}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void steer();
            }
          }}
        />
        <Button
          isDisabled={!canSteer || !sessionId}
          size="sm"
          variant="secondary"
          onPress={() => void steer()}
        >
          Send
        </Button>
        <Button
          isDisabled={!sessionId || confirmingStop}
          size="sm"
          variant="secondary"
          onPress={() => setConfirmingStop(true)}
        >
          Stop
        </Button>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-default-400">
        {state === "sent" && (
          <span>Sent — it reads this at its next step.</span>
        )}
        {state === "failed" && (
          <span>
            Could not send — the task may have finished. Check the run is still
            live.
          </span>
        )}
        {state === "idle" && (
          <span>Sent messages reach the task at its next step.</span>
        )}
        {confirmingStop && (
          <span className="flex items-center gap-1.5">
            <span>Stop this task?</span>
            <Button
              size="sm"
              variant="secondary"
              onPress={() => void stop(false)}
            >
              After this step
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onPress={() => void stop(true)}
            >
              Now
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onPress={() => setConfirmingStop(false)}
            >
              Cancel
            </Button>
          </span>
        )}
      </div>
    </div>
  );
}
