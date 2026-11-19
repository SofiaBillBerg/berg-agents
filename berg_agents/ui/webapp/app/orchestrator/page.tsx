/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
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
 * The orchestrator page — where the user plans WITH the agent.
 *
 * This is the surface the whole TS orchestrator exists for: the user and the
 * orchestrator agree on a shape of work, and the orchestrator delegates to
 * specialists that run as their own durable tasks in berg's Python backend.
 *
 * Deliberately minimal for now. It shows the conversation, the tool activity as
 * it happens, which brain it is running on, and the workflow run id — because
 * an honest surface tells you which run and which model you are talking to.
 * Rich rendering (specialist cards, gates you answer inline) belongs in a later
 * slice, built on what this proves.
 */

"use client";

import React, { useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import {
  RiArrowRightSLine,
  RiCheckLine,
  RiCloseLine,
  RiDeleteBinLine,
  RiPlugLine,
  RiRestartLine,
  RiSearchLine} from "@remixicon/react";

import ThemeToggle from "../components/ThemeToggle.tsx";
import { ChatTranscript } from "../components/ChatTranscript.tsx";
import { Navbar } from "../components/Navbar.tsx";
import { PluginCatalog } from "../components/PluginCatalog.tsx";
import { PluginUISurface } from "../plugins/PluginUISurface.tsx";
import { usePluginSurface } from "../hooks/usePluginSurface";
import { useBackendCatalog } from "../hooks/useBackendCatalog";

import { buildExportMarkdown } from "@/utils/utils";
import { useOrchestratorChat } from "@/harness/useOrchestratorChat";
import { toChatMessage } from "@/harness/messageParts";
import { useSpecialistStates } from "@/harness/useSpecialistStates";
import { API_BASE } from "@/envConfig";
import { Tooltip, TooltipTrigger } from "@/components/ui/tooltip.tsx";
import { Button } from "@/components/ui/button.tsx";
import { Badge } from "@/components/ui/badge.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue} from "@/components/ui/select.tsx";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger} from "@/components/ui/collapsible.tsx";
import { ScrollArea } from "@/components/ui/scroll-area.tsx";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput} from "@/components/ui/input-group.tsx";

/** One routing tier and the models it offers, the best first. */
interface Tier {
  name: string;
  models: string[];
}

/** What GET /api/orchestrator/runs answers. */
interface RunsResponse {
  runs?: {
    runId: string;
    status: string;
    createdAt: string | null;
    hasConversation: boolean;
    preview: string | null;
  }[];
}

/** SWR keys for the orchestrator page's three reads, so a reader and a
    mutation always name the same cache entry. */
const RUNS_KEY = "/api/orchestrator/runs";
const TIERS_KEY = `${API_BASE}/api/tiers`;
const DELEGATE_KEY = `${API_BASE}/api/providers/delegate`;
const SPECIALISTS_KEY = `${API_BASE}/api/providers/specialists`;

/**
 * Read the list of past orchestration runs.
 *
 * @returns The runs, newest first as the route ordered them.
 * @throws When the request fails — SWR then leaves the panel on its
 *   last good list rather than blanking it.
 */
async function fetchRuns(): Promise<RunsResponse> {
  const resp = await fetch(RUNS_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = (await resp.json()) as RunsResponse;
  return { runs: Array.isArray(data.runs) ? data.runs : [] };
}

/**
 * Read the routing tiers.
 *
 * @returns The tiers, or none when the endpoint reports none.
 * @throws When the request fails.
 */
async function fetchTiers(): Promise<{ tiers?: Tier[] }> {
  const resp = await fetch(TIERS_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as { tiers?: Tier[] };
}

/**
 * Read which model delegated specialists run on.
 *
 * @returns The chosen model id, or absent for the backend's default.
 * @throws When the request fails.
 */
async function fetchDelegateModel(): Promise<{ model?: string }> {
  const resp = await fetch(DELEGATE_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as { model?: string };
}

/**
 * Read the per-specialist model overrides.
 *
 * @returns The overrides keyed by agent name, absent agents having no
 *   choice of their own (the delegation default still applies).
 * @throws When the request fails.
 */
async function fetchSpecialistModels(): Promise<{
  models?: Record<string, string>;
}> {
  const resp = await fetch(SPECIALISTS_KEY);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as { models?: Record<string, string> };
}

/**
 * Pull the plain text out of a UI message.
 *
 * @param parts - The message's parts, as the AI SDK holds them.
 * @returns The concatenated text parts.
 */
/*eslint @typescript-eslint/no-unused-vars: "off"*/
function textOf(parts: Array<{ type?: string; text?: string }>): string {
  return parts
    .filter((part) => part?.type === "text" && typeof part.text === "string")
    .map((part) => part.text as string)
    .join("");
}

/**
 * List the tool names a message triggered, so delegation is visible.
 *
 * @param parts - The message's parts.
 * @returns One entry per tool part, with its state.
 */
function toolsOf(
  parts: Array<Record<string, unknown>>,
): Array<{ name: string; state: string }> {
  return parts
    .filter((part) => String(part?.type ?? "").startsWith("tool-"))
    .map((part) => ({
      // "tool-start_specialist" -> "start_specialist"
      name: String(part.type).replace(/^tool-/, ""),
      // The SDK marks a part as input-available, output-available, etc.
      state: String(part.state ?? "called")}));
}

/**
 * What a specialist's chip says about what it is doing.
 *
 * One place, so the words are the same everywhere a specialist is named: the
 * whole point of the strip is that working, parked-on-you, finished and stuck
 * no longer look identical.
 *
 * @param runId - The run being described, if its id has landed.
 * @param state - Its latest state, if it has been read.
 * @returns The label to show.
 */
function liveStateLabel(runId: string, state: string | undefined): string {
  if (!runId) return "starting…";
  if (!state) return "starting…";
  if (state === "waiting") return "waiting on you";
  if (state === "working" || state === "pending") return "working…";
  if (state === "done") return "done";
  return state;
}

/**
 * The orchestrator conversation page, once the browser has taken over.
 *
 * @returns The chat surface for the orchestrator.
 */
function OrchestratorConversation() {
  // Which past run to adopt as this conversation, from the URL: `?run=<id>`.
  // Read once at mount, because adopting changes the conversation's identity
  // (the SDK addresses a reconnect by chat id), so it is a navigation rather
  // than a mid-flight switch. A page opened without it starts fresh.
  // Declared before the hook that takes it.
  const [resumeRunId] = useState<string | undefined>(() => {
    if (typeof window === "undefined") return undefined;
    return new URLSearchParams(window.location.search).get("run") ?? undefined;
  });
  const {
    messages,
    isStreaming,
    error,
    send,
    stop,
    lastRunId,
    pendingApprovals,
    answerApproval,
    model,
    setModel} = useOrchestratorChat(resumeRunId);
  const [input, setInput] = useState("");
  // The specialists this conversation has started, and what each is doing
  // right now. Watched by the page rather than by the orchestrator's goodwill:
  // a specialist used to be invisible until the model chose to look, so the
  // user sat with a finished (or parked, or stuck) specialist and no way to
  // tell which.
  const startedSpecialists = useMemo(() => {
    const rows: { agent: string; model: string; runId: string }[] = [];
    for (const message of messages) {
      for (const part of message.parts ?? []) {
        // Any state, not only `output-available`: a gated tool call passes
        // through input-streaming → approval-requested → approval-responded →
        // output-available, and a strip that waits for the LAST one renders
        // nothing at all while the specialist is genuinely running (found in
        // Sofia's own transcript, where the part sat at approval-responded and
        // the session link never appeared). The agent name is known from the
        // call's input the moment it is parsed, so the chip can show then; the
        // link needs the run id, which only the output carries.
        if (part.type !== "tool-start_specialist") {
          continue;
        }
        // The tool's output arrives either as the object the tool
        // returned or as its JSON text, depending on the transport.
        let output: Record<string, unknown> = {};
        if (typeof part.output === "string") {
          try {
            output = JSON.parse(part.output) as Record<string, unknown>;
          } catch {
            // Unparseable output still leaves the agent name, which
            // the tool call's input carries.
          }
        } else if (typeof part.output === "object") {
          output = part.output as Record<string, unknown>;
        }
        const input = (part.input ?? {}) as { agent?: string };
        const agent =
          String(input.agent ?? "") || String(output.agentName ?? "");
        // Without an agent there is nothing to name yet — the call has not
        // been fully described by the model.
        if (!agent) continue;
        rows.push({
          agent,
          model: String(output.model ?? ""),
          runId: String(output.runId ?? "")});
      }
    }
    return rows;
  }, [messages]);
  const specialistRunIds = useMemo(
    () =>
      startedSpecialists
        .map((row) => row.runId)
        .filter((id): id is string => Boolean(id)),
    [startedSpecialists],
  );
  const specialistStates = useSpecialistStates(specialistRunIds);
  // The routing tiers, so the orchestrator's brain is a choice rather than
  // an environment variable. Configuration rather than conversation state,
  // so it is a shared read: an edit on the backend shows up on the next
  // revalidation without a reload.
  const { data: tiersPayload } = useSWR<{ tiers?: Tier[] }>(
    TIERS_KEY,
    fetchTiers,
  );
  const tiers = tiersPayload?.tiers ?? [];
  // Past orchestration runs. They live in the workflow world's database, not
  // in Python's sessions, so the History tab can never show them — this is
  // their surface. A reload used to lose the run entirely.
  // The stored turns, in the shape berg's store returns (see
  // lib/orchestrator-turns.ts — camelCase, as the rest of this app).
  // One shared read; the delete below writes the same entry, so the panel
  // and any other reader of RUNS_KEY agree without a second fetch.
  const {
    data: runsPayload,
    error: runsError,
    mutate: mutateRuns} = useSWR<RunsResponse>(RUNS_KEY, fetchRuns);
  // Memoized so the array identity is stable across renders: `?? []` on
  // every render would hand `visibleRuns` a new dependency each time.
  const pastRuns = useMemo(() => runsPayload?.runs ?? [], [runsPayload]);
  // The runs panel's search text: fifty runs are only findable if they can be
  // filtered by what they were about, not by their id.
  const [runQuery, setRunQuery] = useState<string>("");
  // The runs the search leaves, newest first as the route ordered them.
  const visibleRuns = useMemo(() => {
    const query = runQuery.trim().toLowerCase();
    if (!query) return pastRuns;
    return pastRuns.filter(
      (run) =>
        (run.preview ?? "").toLowerCase().includes(query) ||
        run.runId.toLowerCase().includes(query) ||
        run.status.toLowerCase().includes(query),
    );
  }, [pastRuns, runQuery]);
  // The run awaiting a second click to be deleted. Null means no delete is
  // pending, so no row shows its "for real" button.
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // A failed run-list read is surfaced in the panel rather than thrown:
  // the live conversation is unaffected either way, and an empty list
  // that silently means "could not reach the server" is a lie.

  // The same side-surface machinery the chat page uses — one hook, so todos
  // and plugin surfaces behave identically here. It wants berg's ChatMessage
  // shape, and the orchestrator speaks UIMessage, so the transcript is
  // converted at this boundary (`toChatMessage`) rather than teaching the
  // hook a second message type.
  const chatMessages = useMemo(
    () => messages.map((message) => toChatMessage(message)),
    [messages],
  );

  // Which model the specialists this page delegates to run on. Loaded from
  // berg's own endpoint and saved back through it, so the choice is the
  // session's (one place) rather than a second copy living in this page.
  // Empty means "not chosen": the backend falls back to its tier default,
  // which is the behavior before this control existed.
  // `chosenOverride` is the value the user just picked: it wins over the
  // read because a POST that has not answered yet must still show the
  // choice, and a failed write is deliberately not rolled back — the next
  // save attempt is the user's to make.
  const { data: delegatePayload } = useSWR<{ model?: string }>(
    DELEGATE_KEY,
    fetchDelegateModel,
  );
  const [chosenOverride, setChosenOverride] = useState<string | null>(null);
  const delegateModel = chosenOverride ?? delegatePayload?.model ?? "";
  // Which specialist runs on which model. `chosenSpecialists` holds the
  // user's edits until a POST answers, exactly like the delegate pair
  // above; a failed write stays visible so the next attempt is theirs.
  const { data: specialistsPayload } = useSWR<{
    models?: Record<string, string>;
  }>(SPECIALISTS_KEY, fetchSpecialistModels);
  const [chosenSpecialists, setChosenSpecialists] = useState<Record<
    string,
    string
  > | null>(null);
  const specialistModels =
    chosenSpecialists ?? specialistsPayload?.models ?? {};

  /**
   * Choose which brain the delegated specialists run on.
   *
   * Sent straight to berg rather than held in page state only: the choice
   * has to reach the Python side, because that is where a specialist run is
   * started (and where it was already being read from before this control
   * existed — no second mechanism).
   *
   * @param value - The chosen model id, or "" for the backend's default.
   */
  async function onDelegateModelChange(value: string): Promise<void> {
    setChosenOverride(value);
    try {
      const resp = await fetch(DELEGATE_KEY, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: value })});
      if (resp.ok) {
        // Confirm the stored choice into the shared entry so a remount
        // (or another reader) starts from what the server accepted,
        // without re-fetching over it.
        void mutate(DELEGATE_KEY, { model: value }, { revalidate: false });
      }
    } catch {
      // The selection stays as chosen locally; the next save attempt is
      // the user's, so a failed write must not silently persist.
    }
  }

  /**
   * Choose which model one specialist runs on.
   *
   * The whole map is written on every change — the endpoint replaces
   * wholesale — so the local edit applies to the map in state, and the
   * server holds a set that can never be half-updated.
   *
   * @param agent - The specialist whose model changes.
   * @param value - The chosen model id, or "" to hand it back to the
   *   delegation default.
   */
  async function onSpecialistModelChange(
    agent: string,
    value: string,
  ): Promise<void> {
    const next = { ...specialistModels, [agent]: value };
    setChosenSpecialists(next);
    try {
      const resp = await fetch(SPECIALISTS_KEY, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ models: next })});
      if (resp.ok) {
        // Confirm the stored set into the shared entry, so a remount
        // (or another reader) starts from what the server accepted.
        void mutate(SPECIALISTS_KEY, { models: next }, { revalidate: false });
      }
    } catch {
      // As with the delegate model: the choice stays visible, and the
      // next save attempt is the user's.
    }
  }

  // The registered specialists, for the pickers' rows, and the flat
  // model list in tier order — the same collection the orchestrator's
  // own selector reads.
  const { agents } = useBackendCatalog();
  const specialistOptions = Array.from(
    new Set(tiers.flatMap((tier) => tier.models)),
  );

  const {
    sidePluginId,
    setSidePluginId,
    showCatalog,
    setShowCatalog,
    pluginView,
    setPluginView,
    sideWidth,
    setSideWidth,
    sideDragging,
    startSideDrag,
    pluginSurfaces,
    activeSurface,
    pluginRefreshKey,
    setPluginCount} = usePluginSurface({ apiBase: API_BASE, messages: chatMessages });

  /**
   * Download the conversation as markdown.
   *
   * Uses the same `buildExportMarkdown` the chat page uses, fed the
   * orchestrator's transcript in its `ChatMessage` shape, so an export from
   * either surface reads the same.
   */
  function exportTranscript(): void {
    // Large transcripts are multi-megabyte blobs: the object URL must
    // outlive the click, so revocation is deferred rather than immediate.
    const markdown = buildExportMarkdown(chatMessages, [], null, null);
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `berg-orchestrator-${new Date()
      .toISOString()
      .slice(0, 10)}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  /**
   * Send what is in the box, then clear it.
   *
   * @param event - The form submission.
   */
  async function onSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    const text = input;
    setInput("");
    await send(text);
  }

  return (
    <>
      {/* The nav is rendered per page, not by the root layout (that is how
                app/context/page.tsx and the others do it). Without it this route
                was a bare screen with no way back — reported 2026-11-12. */}
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Matches the main chat page (app/App.tsx: `w-full
                    max-w-[95vw]`), which this page is the sibling of: a
                    transcript plus a composer. `max-w-3xl` capped it at 768px —
                    about a third of a wide screen — leaving the rest of the
                    viewport empty next to a chat surface that wants the room. */}
        <div className="mx-auto flex h-full w-full max-w-[95vw] flex-col gap-4 p-6">
          <header className="flex items-baseline justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold">Orchestrator</h1>

                <TooltipTrigger>
                  <button
                    aria-label="About Orchestrator"
                    className="cursor-help text-xs opacity-60 hover:opacity-100 focus:outline-none"
                    type="button"
                  >
                    ⓘ
                  </button>

                  <Tooltip placement="right">
                    The orchestrator is the component that coordinates the
                    execution of the workflow. It delegates tasks to the
                    appropriate agents. Follow the specialists the subsessions
                    or stay here, either way the orchestrator keeps track of the
                    progress.
                  </Tooltip>
                </TooltipTrigger>
              </div>

              <p className="text-sm opacity-70">Plan together.</p>
            </div>

            <div className="flex items-center gap-3">
              {/* The run id is shown, not hidden: it is what identifies this
                            orchestration on a reload or a reconnect. */}
              {lastRunId ? (
                <code className="text-xs opacity-60" title="workflow run id">
                  {lastRunId}
                </code>
              ) : null}
              {/* The way out of a restored run. The `?run=` param is sticky
                            across sends, so a restored conversation had no
                            exit: every next message continued the restored
                            turn. Shown exactly when one is being continued. */}
              {resumeRunId ? (
                <button
                  className="rounded border border-current/30 px-2 py-0.5 text-xs"
                  title="Leave this restored run and start a fresh conversation"
                  type="button"
                  onClick={() => {
                    // A full load on purpose: resumeRunId is read once
                    // at mount (see above), and a router.push would keep
                    // this restored conversation mounted instead of
                    // starting a fresh one.
                    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
                    window.location.assign("/orchestrator");
                  }}
                >
                  New conversation
                </button>
              ) : null}
            </div>
          </header>

          {/* Past runs — context, not content. It used to be fifty opaque run ids
                    with full-size buttons, which pushed the transcript off a
                    laptop screen (the only thing this page is for). Now: what
                    the run was ABOUT, a search field, and icon-sized actions.
                    Collapsed by default: fifty runs of history are context, not
                    content — the conversation is. Expanded on demand. */}
          {runsError ? (
            <p className="px-3 text-xs text-red-500">
              Past runs unavailable: {runsError.message}
            </p>
          ) : null}
          {pastRuns.length > 0 ? (
            <Collapsible className="rounded border border-border">
              <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-3 py-1.5">
                <RiArrowRightSLine
                  aria-hidden="true"
                  className="size-3.5 opacity-70 transition-transform [[aria-expanded=true]_&]:rotate-90"
                />
                <span className="text-xs font-medium opacity-80">
                  Past runs ({pastRuns.length})
                </span>
              </CollapsibleTrigger>
              <CollapsibleContent className="border-t border-border">
                <div className="px-3 py-1.5">
                  <InputGroup className="w-full">
                    <InputGroupAddon>
                      <RiSearchLine />
                    </InputGroupAddon>
                    <InputGroupInput
                      aria-label="Search past runs"
                      placeholder="Search runs"
                      value={runQuery}
                      onChange={(event) => setRunQuery(event.target.value)}
                    />
                    {runQuery ? (
                      <InputGroupAddon align="inline-end">
                        <InputGroupButton
                          aria-label="Clear search"
                          onPress={() => setRunQuery("")}
                        >
                          <RiCloseLine />
                        </InputGroupButton>
                      </InputGroupAddon>
                    ) : null}
                  </InputGroup>
                  {/* Capped and scrolling on its own: fifty runs would otherwise
                    push the whole page past its scroll container. The outer
                    page scrolls for the conversation, not for this list. */}
                  <ScrollArea className="max-h-72">
                    <ul className="flex flex-col">
                      {visibleRuns.map((run) => (
                        <li
                          key={run.runId}
                          className="flex items-center gap-2 px-3 py-1 text-xs"
                        >
                          {/* What the run was ABOUT — the opening message, or an
                            honest label for the runs that predate the store. */}
                          {/* What the run was ABOUT — the opening message, or an
                            honest label for the runs that predate the store. */}
                          <span className="min-w-0 flex-1 truncate">
                            {run.preview ?? (
                              <span
                                className="opacity-60"
                                title="This run has the agent's log in the workflow world, but no stored conversation — there is nothing to restore."
                              >
                                agent log only
                              </span>
                            )}
                          </span>
                          <Badge
                            variant={
                              run.status === "completed"
                                ? "secondary"
                                : "outline"
                            }
                          >
                            {run.status}
                          </Badge>
                          <time className="opacity-60 tabular-nums">
                            {run.createdAt
                              ? new Date(run.createdAt).toLocaleString()
                              : ""}
                          </time>
                          {/* Restore, not just view: the page navigates with this
                            run's id, and on mount the hook adopts the stored
                            conversation — so the next message continues this
                            turn. Offered only where a conversation exists: a
                            log-only run has nothing to restore, and clicking
                            Restore there produced a 404 read and a hydration
                            crash. */}
                          {run.hasConversation ? (
                            <TooltipTrigger>
                              <Button
                                aria-label="Restore this run"
                                size="xs"
                                variant="ghost"
                                onPress={() => {
                                  // A full load on purpose: the page
                                  // adopts `?run=` on mount (see
                                  // resumeRunId above), which a client
                                  // navigation would not re-run.
                                  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
                                  window.location.assign(
                                    `/orchestrator?run=${run.runId}`,
                                  );
                                }}
                              >
                                <RiRestartLine data-icon="inline-start" />
                              </Button>
                              <Tooltip placement="top">
                                Restore this conversation
                              </Tooltip>
                            </TooltipTrigger>
                          ) : null}
                          {/* Delete, in two steps on purpose: the first click
                            asks, the second does it. Removing a conversation is
                            Sofia's decision, and a single mis-click is not
                            one. */}
                          {confirmDelete === run.runId ? (
                            <Button
                              aria-label="Delete for real"
                              size="xs"
                              variant="destructive"
                              onPress={() => {
                                void (async () => {
                                  setConfirmDelete(null);
                                  // Optimistic: drop the row at once, then
                                  // confirm against the server. A failed
                                  // delete rolls the row back rather than
                                  // leaving a row the panel insists is gone.
                                  await mutateRuns(
                                    async (
                                      current: RunsResponse | undefined,
                                    ) => {
                                      const resp = await fetch(
                                        `/orchestrator/runs/${encodeURIComponent(run.runId)}`,
                                        { method: "DELETE" },
                                      );
                                      if (!resp.ok) {
                                        throw new Error(`HTTP ${resp.status}`);
                                      }
                                      return {
                                        runs: (current?.runs ?? []).filter(
                                          (r) => r.runId !== run.runId,
                                        )};
                                    },
                                    {
                                      optimisticData: {
                                        runs: pastRuns.filter(
                                          (r) => r.runId !== run.runId,
                                        )},
                                      rollbackOnError: true,
                                      revalidate: false},
                                  ).catch(() => {
                                    // The row comes back on its own from the
                                    // next revalidation; nothing to restore.
                                  });
                                })();
                              }}
                            >
                              <RiCheckLine data-icon="inline-start" />
                            </Button>
                          ) : (
                            <TooltipTrigger>
                              <Button
                                aria-label="Delete this run"
                                size="xs"
                                variant="ghost"
                                onPress={() => setConfirmDelete(run.runId)}
                              >
                                <RiDeleteBinLine data-icon="inline-start" />
                              </Button>
                              <Tooltip placement="top">
                                {run.hasConversation
                                  ? "Delete this conversation (asks twice)"
                                  : "Delete this log entry (asks twice)"}
                              </Tooltip>
                            </TooltipTrigger>
                          )}
                        </li>
                      ))}
                      {visibleRuns.length === 0 ? (
                        <li className="px-3 py-2 text-xs opacity-60">
                          No run matches that search.
                        </li>
                      ) : null}
                    </ul>
                  </ScrollArea>
                </div>
              </CollapsibleContent>
            </Collapsible>
          ) : null}

          {/* The same controls the chat page offers, because the
                        orchestrator is where planning happens: which model,
                        which agent, whose todos, which plugins. One button per
                        plugin that declared + shipped a surface, plus the
                        catalog — reused rather than reimplemented. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {pluginSurfaces.map((surface) => {
              const decl = surface.ui as { label?: unknown } | null;
              const label =
                typeof decl?.label === "string" ? decl.label : "Plugin";
              const isOpen = sidePluginId === surface.pluginId;
              return (
                <Button
                  key={surface.pluginId}
                  aria-label={isOpen ? `Hide ${label}` : `Show ${label}`}
                  size="xs"
                  variant="secondary"
                  onPress={() => {
                    setSidePluginId((prev) =>
                      prev === surface.pluginId ? null : surface.pluginId,
                    );
                  }}
                >
                  {label}
                </Button>
              );
            })}
            <Button
              aria-label={showCatalog ? "Hide plugins" : "Show plugins"}
              size="xs"
              variant="secondary"
              onPress={() => {
                setShowCatalog((prev) => !prev);
                // The catalog owns the right-hand side on its own.
                setSidePluginId(null);
              }}
            >
              <RiPlugLine data-icon="inline-start" />
              Plugins
            </Button>
            <span className="flex-1" />
            {/* Model choices in one labeled row: the orchestrator's own
                    brain, and the specialists' brains. One global select
                    could not express "planner cheap, implementer strong",
                    so each specialist gets a selector of its own — the
                    old single value stays as the "all specialists" row,
                    which is the fallback any specialist without a choice
                    of its own still resolves through.
                    Grouped by tier so the ordering berg configures stays
                    visible, not a flat list of names. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs opacity-70">Orchestrator runs on</span>
              <Select
                aria-label="Orchestrator runs on"
                className="min-w-56"
                selectedKey={model || "__default"}
                onSelectionChange={(key) =>
                  setModel(key === "__default" ? "" : String(key))
                }
              >
                <SelectTrigger size="sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem id="__default">
                    default ({tiers.flatMap((t) => t.models)[0] ?? "configured"}
                    )
                  </SelectItem>
                  {/* Flat, in tier order, deduplicated: a model that sits
                          in two tiers is the same model, and a collection
                          may not list one twice. */}
                  {specialistOptions.map((name) => (
                    <SelectItem key={name} id={name}>
                      {name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Collapsible>
                <CollapsibleTrigger className="flex items-center gap-1 text-xs opacity-70 hover:opacity-100">
                  Specialists run on
                  <RiArrowRightSLine className="transition-transform group-aria-expanded:rotate-90" />
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-2">
                  <div className="flex max-h-72 w-72 flex-col gap-2 overflow-y-auto rounded-md border border-border bg-surface/60 p-2">
                    {/* The global fallback: what a specialist with no
                        choice of its own runs on. */}
                    <div className="flex items-center gap-2">
                      <span className="w-28 shrink-0 text-xs opacity-70">
                        all specialists
                      </span>
                      <Select
                        aria-label="All specialists run on"
                        className="min-w-0 flex-1"
                        selectedKey={delegateModel || "__default"}
                        onSelectionChange={(key) => {
                          void onDelegateModelChange(
                            key === "__default" ? "" : String(key),
                          );
                        }}
                      >
                        <SelectTrigger size="sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem id="__default">
                            specialists: default (tier)
                          </SelectItem>
                          {specialistOptions.map((name) => (
                            <SelectItem key={name} id={name}>
                              {name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {/* One row per specialist berg registers, each with
                        its own model choice. An override wins over the
                        global row; "default (tier)" hands it back. */}
                    {agents.map((agent) => {
                      const chosen = specialistModels[agent.name] ?? "";
                      return (
                        <div
                          key={agent.name}
                          className="flex items-center gap-2"
                          title={agent.description}
                        >
                          <span className="w-28 shrink-0 truncate text-xs">
                            {agent.name}
                          </span>
                          <Select
                            aria-label={`${agent.name} runs on`}
                            className="min-w-0 flex-1"
                            selectedKey={chosen || "__default"}
                            onSelectionChange={(key) => {
                              void onSpecialistModelChange(
                                agent.name,
                                key === "__default" ? "" : String(key),
                              );
                            }}
                          >
                            <SelectTrigger size="sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem id="__default">
                                default (tier)
                              </SelectItem>
                              {specialistOptions.map((name) => (
                                <SelectItem key={name} id={name}>
                                  {name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      );
                    })}
                    {agents.length === 0 && (
                      <span className="text-xs opacity-70">
                        No specialists registered.
                      </span>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
            {/* The same toggle the chat page carries: the theme is a
                            property of the app, not of one route, and the
                            orchestrator page used to be the only one without it
                            (dark mode here meant switching to Chat first). */}
            <ThemeToggle />
            <button
              className="rounded border border-current/30 px-2 py-1 text-xs"
              type="button"
              onClick={exportTranscript}
            >
              ⬇ Export
            </button>
          </div>

          {/* Transcript and side surface side by side, exactly as
                        the chat page lays them out: the transcript keeps its
                        own flex column so heights match, and a drag divider
                        lets the surface be widened. */}
          {/* What has been delegated, and to what — one line per started
                        specialist, from its actual tool result. A run used to
                        start silently: the only trace was a tool card whose
                        output you had to open, and nothing named the model.
                        Empty until the first specialist starts.

                        OUTSIDE the transcript row on purpose: inside it these
                        became a flex item whose long run ids could not shrink,
                        and a narrow window squeezed the transcript — and the
                        composer, and Stop — out of the viewport. The run id is
                        truncated here and complete in the tooltip. */}
          {startedSpecialists.length > 0 ? (
            <ul className="mb-2 flex flex-wrap items-center gap-2 text-xs opacity-80">
              {startedSpecialists.map((row, index) => (
                <li
                  key={`${row.runId || row.agent}-${index}`}
                  className="flex min-w-0 items-center gap-1.5 rounded border border-current/20 px-2 py-1"
                >
                  <span className="font-medium">
                    {row.agent || "specialist"}
                  </span>
                  {/* What it is doing, live. Until this was watched by the page,
                      a specialist was invisible from the moment it was
                      delegated to the moment the orchestrator happened to look:
                      working, waiting on a decision, finished, and stuck all
                      read exactly the same — nothing. */}
                  <span className="opacity-70">
                    {liveStateLabel(row.runId, specialistStates[row.runId])}
                  </span>
                  {/* The link IS the point of this strip. Delegating used to mean
                      hiding a run's id in a tool card and summarizing what came
                      back; the run id is now the door into that specialist's
                      session — follow it in, work there, and come back. */}
                  {row.runId ? (
                    <a
                      className="overflow-hidden text-ellipsis whitespace-nowrap underline opacity-70 hover:opacity-100"
                      href={`/specialist/${encodeURIComponent(row.runId)}`}
                      title={`Open ${row.agent}'s session (${row.runId})`}
                    >
                      open session →
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          <div className="mb-2 flex min-h-0 flex-1 gap-0">
            <div className="flex min-w-0 flex-1 flex-col">
              {/* The real transcript, not a reimplementation: it is
                            what gives chat its Streamdown rendering (markdown,
                            mermaid, code highlighting), collapsible tool cards
                            and reasoning traces. The orchestrator was showing
                            raw text before — the same words with none of the
                            reading (reported 2026-11-12 from a side-by-side
                            screenshot with the chat page). */}
              <ChatTranscript
                hitlRequest={undefined}
                isAnimating={isStreaming}
                isExecuting={isStreaming}
                transcript={chatMessages}
              />
            </div>

            {sidePluginId !== null || showCatalog ? (
              <>
                <div
                  aria-orientation="vertical"
                  aria-valuemax={Math.max(320, 1200)}
                  aria-valuemin={280}
                  aria-valuenow={sideWidth}
                  className={`w-1 shrink-0 cursor-col-resize rounded bg-border transition-colors hover:bg-primary ${
                    sideDragging ? "bg-primary" : ""
                  }`}
                  role="separator"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "ArrowLeft")
                      setSideWidth((width) =>
                        Math.min(
                          Math.max(320, window.innerWidth - 420),
                          width + 24,
                        ),
                      );
                    if (event.key === "ArrowRight")
                      setSideWidth((width) => Math.max(280, width - 24));
                  }}
                  onPointerDown={startSideDrag}
                />
                {sidePluginId && activeSurface ? (
                  <PluginUISurface
                    key={sidePluginId}
                    className={pluginView === "canvas" ? "flex-1" : "shrink-0"}
                    pluginId={sidePluginId}
                    refreshKey={pluginRefreshKey}
                    style={
                      pluginView === "canvas" ? undefined : { width: sideWidth }
                    }
                    ui={activeSurface.ui}
                    view={pluginView}
                    onClose={() => setSidePluginId(null)}
                    onCount={setPluginCount}
                    onToggleView={() =>
                      setPluginView((view) =>
                        view === "panel" ? "canvas" : "panel",
                      )
                    }
                  />
                ) : (
                  <PluginCatalog
                    className="shrink-0"
                    style={{ width: sideWidth }}
                    onClose={() => setShowCatalog(false)}
                  />
                )}
              </>
            ) : null}
          </div>

          {/* The orchestrator's pause, made answerable. Without this the
                        run stops and nothing releases it — the agent asks, the user
                        decides, and only then does the specialist start or its gate
                        open. */}
          {pendingApprovals.length > 0 ? (
            <div className="space-y-2 rounded border border-amber-500/40 p-3">
              <p className="text-sm font-medium">
                The orchestrator is waiting on you
              </p>
              {pendingApprovals.map((approval) => (
                <div key={approval.approvalId} className="space-y-1">
                  <p className="text-xs opacity-70">
                    It wants to run{" "}
                    <code className="font-semibold">{approval.toolName}</code>
                    {approval.input ? (
                      <span className="opacity-80">
                        {" "}
                        — {JSON.stringify(approval.input).slice(0, 300)}
                      </span>
                    ) : null}
                  </p>
                  <div className="flex gap-2">
                    <button
                      className="rounded border border-current/30 px-2 py-1 text-xs"
                      type="button"
                      onClick={() => answerApproval(approval.approvalId, true)}
                    >
                      Allow
                    </button>
                    <button
                      className="rounded border border-current/30 px-2 py-1 text-xs"
                      type="button"
                      onClick={() => answerApproval(approval.approvalId, false)}
                    >
                      Refuse
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          {error ? (
            <p className="rounded border border-red-500/40 p-2 text-sm text-red-500">
              {error}
            </p>
          ) : null}

          <form className="flex gap-2" onSubmit={onSubmit}>
            <input
              className="flex-1 rounded border border-current/20 bg-transparent px-3 py-2 text-sm"
              placeholder="What should we work on?"
              value={input}
              onChange={(event) => setInput(event.target.value)}
            />
            {isStreaming ? (
              <button
                className="rounded border border-current/30 px-3 py-2 text-sm"
                type="button"
                onClick={stop}
              >
                Stop
              </button>
            ) : (
              <button
                className="rounded border border-current/30 px-3 py-2 text-sm"
                disabled={!input.trim()}
                type="submit"
              >
                Send
              </button>
            )}
          </form>
        </div>
      </div>
    </>
  );
}

/**
 * The page: the conversation, after the browser has taken over.
 *
 * The mount guard is not decoration. The conversation's identity comes from
 * the URL (`?run=<id>`), and only the browser can read it — the server pass
 * has no `window`, so it renders a fresh conversation while the client's
 * first render adopts a past one. That divergence is a React #418 hydration
 * mismatch (it hit every restored run that had no stored conversation), and
 * the `useChat` hook keyed by that id re-initializes on the mismatch instead
 * of restoring. Rendering the placeholder until mounted makes both passes
 * identical; the real page then mounts ONCE, on the client, with the param
 * already in hand and the chat id correct from its first render.
 *
 * @returns The chat surface for the orchestrator.
 */
export default function OrchestratorPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Wait for hydration.
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-6 text-sm opacity-60">Loading the orchestrator…</div>
    );
  }
  return <OrchestratorConversation />;
}
