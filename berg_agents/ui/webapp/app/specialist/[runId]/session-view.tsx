"use client";

// A client component, like every page that renders a live session: the stream,
// the polling and the actions all run in the browser. Split from the route's
// page module because `export const instant` is a route segment config, and
// Next accepts it only from a Server Component module — the page stays the
// server shell, this is the live surface.

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import ChatTranscript from "@/app/components/ChatTranscript";
import { Navbar } from "@/app/components/Navbar";
import { useSpecialistSession } from "@/harness/useSpecialistSession";

/**
 * A specialist's session, as a place you can be.
 *
 * Not a view of a task: the specialist's own transcript, its gates as decisions
 * on that transcript, and a composer so work can be sent into the run while it
 * runs. The transcript is the same `ChatTranscript` the chat and the orchestrator
 * use — one renderer, because the stream is the same Vercel AI frames in one
 * protocol — and the actions are the run's own routes (answer its gate, steer it,
 * stop it), reached from here instead of through the orchestrator.
 *
 * This is the surface the orchestrator's delegation should open into: the user
 * follows the specialist into its session and works there, and the specialist
 * reports back — rather than a run that happens somewhere else and hands back a
 * summary.
 *
 * @param props - The run whose session this is.
 * @returns The specialist's session.
 */
export default function SpecialistSessionView({ runId }: { runId: string }) {
  const session = useSpecialistSession(runId);
  const [steerText, setSteerText] = useState("");
  // The conversation this session was launched from, when the link that
  // carried here said so: the way back lands in THAT conversation, not in
  // a new one. Without it the orchestrator's own default is the honest
  // fallback.
  const fromRun = useSearchParams().get("from");
  const backHref = fromRun
    ? `/orchestrator?run=${encodeURIComponent(fromRun)}`
    : "/orchestrator";

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex h-full w-full max-w-[95vw] flex-col gap-4 p-6">
          <header className="flex items-baseline justify-between gap-4">
            <div>
              <h1 className="text-lg font-semibold">Session</h1>
              {/* The run id is shown, not hidden: it is what the
                                orchestrator's turn and every action address. */}
              <code className="text-xs opacity-60">{runId}</code>
            </div>
            {/* Home is the default: this is an excursion into a
                            specialist's session, and the way back is always
                            visible rather than a browser gesture. */}
            <a
              className="rounded border border-current/30 px-2 py-1 text-xs"
              href={backHref}
            >
              ← Back to your session
            </a>
          </header>

          {/* What the specialist is doing, and the gates it is waiting
                        on. A gate is a decision, not a log line: the tool it
                        wants to run and the arguments it wants to use, with the
                        run's own words when it has any. */}
          {session.pending.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {session.pending.map((call) => (
                <li
                  key={call.tool_call_id}
                  className="rounded border border-warning p-3 text-sm"
                >
                  <p className="mb-2 font-medium">
                    {session.state === "waiting"
                      ? "Waiting on your decision"
                      : "Working"}
                  </p>
                  <p className="mb-1 opacity-80">
                    wants to run <code>{call.tool_name}</code>
                  </p>
                  <pre className="mb-2 overflow-x-auto rounded bg-code-background p-2 text-xs">
                    {JSON.stringify(call.args, null, 2)}
                  </pre>
                  <div className="flex gap-2">
                    <button
                      className="rounded border border-current/30 px-3 py-1 text-xs"
                      type="button"
                      onClick={() => session.answer(call, true)}
                    >
                      Allow
                    </button>
                    <button
                      className="rounded border border-current/30 px-3 py-1 text-xs"
                      type="button"
                      onClick={() => session.answer(call, false)}
                    >
                      Refuse
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}

          {/* The specialist's own work: reasoning, tool calls, and what
                        it said, as they arrive. */}
          <ChatTranscript
            hitlRequest={null}
            isAnimating={session.live}
            isExecuting={session.live}
            transcript={session.transcript}
          />

          {session.error ? (
            <p className="text-xs text-destructive">{session.error}</p>
          ) : null}

          {/* The composer. Sending here steers the run rather than
                        starting a new one — work continues in this session. */}
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const text = steerText.trim();
              if (!text) return;
              setSteerText("");
              session.steer(text);
            }}
          >
            <input
              className="flex-1 rounded border border-current/20 bg-transparent px-3 py-2 text-sm"
              placeholder="Send into this session…"
              value={steerText}
              onChange={(event) => setSteerText(event.target.value)}
            />
            <button
              className="rounded border border-current/30 px-3 py-2 text-sm"
              type="submit"
            >
              Send
            </button>
            <button
              className="rounded border border-danger px-3 py-2 text-sm text-danger"
              type="button"
              onClick={() => session.stop()}
            >
              Stop
            </button>
          </form>
        </div>
      </div>
    </>
  );
}
