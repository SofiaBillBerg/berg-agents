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
 * along with this program.  If not, see <https://gnu.org/licenses/agpl.html>.
 */

"use client";

import type { ChatMessage } from "@/harness";

import { MessageList } from "@/app/components/MessageList.tsx";

/* A settled turn: one assistant group carrying reasoning, a delegated
   specialist (whose session link stands in for the live run's stream),
   a ran call, a denied call and a failed call - the whole Trace
   vocabulary in one fixture, so the transcript can be exercised
   without a session, a backend, or a model. */
const settledTranscript: ChatMessage[] = [
  {
    id: "u1",
    role: "user",
    content: "Create the probe file, then read it back."},
  {
    id: "a1",
    role: "assistant",
    content: "The file is created and read back.",
    reasoning:
      "The task is a one-line file write, so the implementation specialist handles it.",
    toolCalls: [
      {
        tool: "start_specialist",
        toolCallId: "c1",
        input: JSON.stringify(
          { agent: "implementation", task: "Create suggestions/x.txt" },
          null,
          2,
        ),
        state: "output-available",
        output: JSON.stringify({ runId: "wrun_preview" }, null, 2)},
      {
        tool: "read_file",
        toolCallId: "c2",
        input: JSON.stringify({ file_path: "suggestions/x.txt" }, null, 2),
        state: "output-available",
        output: "probe"},
      {
        tool: "edit_file",
        toolCallId: "c3",
        input: JSON.stringify({ file_path: "suggestions/x.txt" }, null, 2),
        state: "output-denied"},
      {
        tool: "grep",
        toolCallId: "c4",
        input: JSON.stringify({ pattern: "probe" }, null, 2),
        state: "output-error",
        output: "no matches"}]}];

/* The same turn mid-stream: reasoning open, the specialist running, and
   one call waiting on approval. */
const liveTranscript: ChatMessage[] = [
  {
    id: "a2",
    role: "assistant",
    content: "",
    reasoning: "Checking whether the file lands where the task said.",
    toolCalls: [
      {
        tool: "start_specialist",
        toolCallId: "c1",
        input: JSON.stringify(
          { agent: "implementation", task: "Create suggestions/x.txt" },
          null,
          2,
        ),
        state: "input-available"},
      {
        tool: "write_file",
        toolCallId: "c5",
        input: JSON.stringify({ file_path: "suggestions/x.txt" }, null, 2),
        state: "approval-requested"}]}];

/**
 * A fixture page for the transcript rows: renders the settled and
 * streaming shapes of the Trace vocabulary side by side. It touches no
 * session and no backend, so the rows can be clicked through without
 * a model or a stored conversation.
 *
 * @returns The preview page
 */
export default function TranscriptPreviewPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 p-6">
      <div>
        <h1 className="text-lg font-bold">Transcript preview</h1>
        <p className="text-sm text-muted-foreground">
          Fixture-only render of the Trace vocabulary — no session, no backend.
          Click rows to check their open/close behavior.
        </p>
      </div>
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Settled turn
        </h2>
        <MessageList history={settledTranscript} />
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">
          Streaming turn
        </h2>
        <MessageList history={liveTranscript} isAnimating={true} />
      </section>
    </div>
  );
}
