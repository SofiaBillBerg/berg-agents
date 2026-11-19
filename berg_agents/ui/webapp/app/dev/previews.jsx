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

import { ComponentPreview, Previews } from "@react-buddy/ide-toolbox";

import App from "../app/App.tsx";
import InputBar from "../app/components/InputBar.tsx";
import MarkdownRenderer from "../app/components/MarkdownRenderer.tsx";
import MessageList from "../app/components/MessageList.tsx";
import ProviderSelector from "../app/components/ProviderSelector.tsx";

import { PaletteTree } from "./palette";

/* A settled turn: one assistant group carrying reasoning, a delegated
   specialist (with its session link, since a live specialist streams
   into its own run), a ran call, a denied call and a failed call - the
   whole Trace vocabulary in one fixture so the transcript surface can
   be exercised without a session or a model. */
const settledTranscript = [
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

/* The same turn mid-stream: the reasoning open and the specialist still
   running, with a call waiting on approval. */
const liveTranscript = [
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

const ComponentPreviews = () => {
  return (
    <Previews palette={<PaletteTree />}>
      <ComponentPreview path="/App">
        <App />
      </ComponentPreview>
      <ComponentPreview path="/InputBar">
        <InputBar />
      </ComponentPreview>
      <ComponentPreview path="/MarkdownRenderer">
        <MarkdownRenderer />
      </ComponentPreview>
      <ComponentPreview path="/MessageList">
        <MessageList />
      </ComponentPreview>
      <ComponentPreview path="/MessageListTranscript">
        <MessageList history={settledTranscript} />
      </ComponentPreview>
      <ComponentPreview path="/MessageListLive">
        <MessageList history={liveTranscript} isAnimating={true} />
      </ComponentPreview>
      <ComponentPreview path="/ProviderSelector">
        <ProviderSelector />
      </ComponentPreview>
      <ComponentPreview path="/PaletteTree">
        <PaletteTree />
      </ComponentPreview>
    </Previews>
  );
};

export default ComponentPreviews;
