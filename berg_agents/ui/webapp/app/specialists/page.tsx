"use client";

// The specialists, as a place to start from.
//
// A specialist is a full-scale agent with its own run: this index makes
// those runs findable the way any launched subagent is — by agent, by
// status, by the task it was given — so a session can be entered and
// worked in without going through the conversation that launched it.

import { useEffect, useState } from "react";
import Link from "next/link";
import useSWR from "swr";

import { Navbar } from "@/app/components/Navbar";
import { Badge } from "@/components/ui/badge.tsx";

/** One specialist run, as the listing answers it. */
interface SpecialistSession {
  runId: string;
  agent: string;
  status: string;
  createdAt: string | null;
  task: string;
}

/**
 * Read the specialist sessions.
 *
 * @returns The sessions, newest first as the route ordered them.
 * @throws When the request fails — SWR then leaves the list on its last
 *   good rows rather than blanking it.
 */
async function fetchSpecialists(): Promise<{
  specialists?: SpecialistSession[];
}> {
  const resp = await fetch("/api/specialists");
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as { specialists?: SpecialistSession[] };
}

/**
 * Which badge variant a run's status reads in: work still moving is
 * loud, finished work is quiet, and a failed run says so.
 *
 * @param status - The run's raw status.
 * @returns The badge variant.
 */
function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" {
  if (status === "failed" || status === "error") return "destructive";
  if (status === "working" || status === "running" || status === "pending")
    return "default";
  return "secondary";
}

/**
 * The specialist sessions: every run a specialist has, newest first,
 * each one a door into that session.
 *
 * @returns The specialists index.
 */
export default function SpecialistsPage() {
  const { data, error } = useSWR<{ specialists?: SpecialistSession[] }>(
    "/api/specialists",
    fetchSpecialists,
  );
  const sessions = data?.specialists ?? [];
  // A short poll so a session started elsewhere (the orchestrator's
  // delegation) appears without a reload — the list is a live index of
  // live runs.
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((n) => n + 1), 10000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[95vw] flex-col gap-4 p-6">
          <header className="flex flex-col gap-1">
            <h1 className="text-lg font-semibold">Specialists</h1>
            <p className="text-sm text-muted-foreground">
              Every specialist session, newest first. Each one is a run of its
              own — open it to see its transcript, answer its gates, and steer
              it while it works.
            </p>
          </header>

          {error ? (
            <p className="text-sm text-destructive">
              Could not list the specialist sessions: {String(error)}
            </p>
          ) : null}

          {sessions.length === 0 && !error ? (
            <p className="text-sm text-muted-foreground">
              No specialist sessions yet. Delegating from the orchestrator
              starts one.
            </p>
          ) : null}

          <ul className="flex flex-col gap-2">
            {sessions.map((session) => (
              <li
                key={session.runId}
                className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3"
              >
                <Badge variant="secondary">{session.agent}</Badge>
                <Badge variant={statusVariant(session.status)}>
                  {session.status || "unknown"}
                </Badge>
                <span className="min-w-0 flex-1 truncate text-sm">
                  {session.task || "(no task recorded)"}
                </span>
                <span className="text-xs text-muted-foreground">
                  {session.createdAt
                    ? new Date(session.createdAt).toLocaleString()
                    : ""}
                </span>
                <Link
                  className="rounded border border-current/30 px-3 py-1 text-xs"
                  href={`/specialist/${encodeURIComponent(session.runId)}`}
                >
                  Open session →
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
