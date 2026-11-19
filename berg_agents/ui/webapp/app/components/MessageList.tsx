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

import type {
  ChatMessage,
  DelegatedTaskInCard,
  MessageParts,
  MessageToolCall} from "@/harness";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Button } from "@heroui/react";
import {
  RiCheckLine,
  RiErrorWarningLine,
  RiUserLine,
  RiFileEditLine,
  RiFileTextLine,
  RiFolderLine,
  RiLoaderLine,
  RiRobotLine,
  RiSearchLine,
  RiSparklingLine,
  RiTerminalLine,
  RiToolsLine} from "@remixicon/react";
import useSWR from "swr";

import { MarkdownRenderer } from "./MarkdownRenderer.tsx";
import DelegationTaskControls from "./DelegationTaskControls.tsx";

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle} from "@/components/ui/trace";
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageHeader} from "@/components/ui/message";
import { CodeBlock, CodeBlockContent } from "@/components/ui/code-block";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemMedia,
  ItemTitle} from "@/components/ui/item";
import {
  CATALOG_KEYS,
  CATALOG_SWR_OPTIONS,
  fetchPlugins,
  type PluginInfo} from "@/lib/backendCatalog";

/**
 * The tool names that belong to a plugin surface, as a set derived from
 * the plugin catalog. Built during render from the shared SWR entry so
 * the transcript that reads it is never a render behind the catalog —
 * this used to live in a module-level Set mutated by an Effect, which
 * meant the Set changed AFTER the render that needed it.
 *
 * @returns Every tool name any installed plugin advertises.
 */
function usePluginToolNames(): Set<string> {
  const { data: plugins } = useSWR<PluginInfo[]>(
    CATALOG_KEYS.plugins,
    fetchPlugins,
    CATALOG_SWR_OPTIONS,
  );
  return useMemo(() => {
    const names = new Set<string>();
    for (const p of plugins ?? []) {
      if (p && Array.isArray(p.tools)) {
        for (const t of p.tools) {
          if (typeof t === "string") names.add(t);
        }
      }
    }
    return names;
  }, [plugins]);
}

/**
 * The transcript this component renders. The shape is the harness's own
 * `ChatMessage` — the copy that used to live here had already drifted
 * from it (it knew nothing of a tool call's `children`), and one shape
 * for one message is the rule.
 */
export interface MessageListProps {
  history?: ChatMessage[];
  /** Whether the assistant turn is currently streaming (animates code blocks). */
  isAnimating?: boolean;
  /** Answer a delegated task's gated write. Absent means the caller has
        no such surface (export, tests), and the buttons are not drawn. */
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
}

/**
 * One assistant turn's reasoning, as a Trace row following the Reasoning
 * pattern (ui.shadcn.com/docs/ai-elements/aria/reasoning, built on the
 * shadcn/ui `Trace` primitives): a plain row reading "Thinking", spinner
 * running, while the model works — and a collapsible "Thought" row once
 * there is text to show. It opens while the turn streams and closes when
 * it ends, unless the reader opened or closed it themselves: their choice
 * wins, via the uncontrolled `open ?? running` open state.
 *
 * @param props - The reasoning text and whether the turn still streams
 * @returns The reasoning Trace row
 */
function ReasoningLine({
  text,
  isAnimating}: {
  text: string;
  /** Whether the turn is still streaming (keeps the row open). */
  isAnimating?: boolean;
}) {
  // undefined means the reader has not chosen yet, so the streaming state
  // drives the open state until they take over with a click.
  const [open, setOpen] = useState<boolean | undefined>(undefined);
  const running = Boolean(isAnimating);
  const line = (
    <TraceLine status={running ? "running" : undefined}>
      <TraceIcon>
        {running ? <RiLoaderLine className="animate-spin" /> : <RiCheckLine />}
      </TraceIcon>
      <TraceTitle>{running ? "Thinking" : "Thought"}</TraceTitle>
    </TraceLine>
  );
  // Before any text lands there is nothing to open: a plain row is the
  // whole component, exactly as the pattern prescribes.
  if (text.trim() === "") {
    return <Trace>{line}</Trace>;
  }
  return (
    <Trace>
      <TraceCollapsible isExpanded={open ?? running} onExpandedChange={setOpen}>
        <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <MarkdownRenderer content={text} isAnimating={isAnimating} />
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/**
 * The icon one tool line carries: what kind of work the call is, at a
 * glance. A plugin surface's tool keeps its own marker so plugin
 * activity (todos) reads as plugin work, not generic tool output — the
 * full interactive surface still lives in the side panel.
 *
 * @param props - The tool name and whether it belongs to a plugin surface
 * @returns The icon element for the row
 */
function ToolLineIcon({ tool, isPlugin }: { tool: string; isPlugin: boolean }) {
  if (isPlugin) return <RiSparklingLine />;
  // Delegation-shaped calls spawn a sub-agent; the robot icon already
  // reads as "an agent ran", and phase 3 gives them the Subagent pattern.
  if (tool.endsWith("_task")) return <RiRobotLine />;
  if (tool.startsWith("run_") || tool.includes("command"))
    return <RiTerminalLine />;
  if (tool.includes("edit") || tool.includes("write"))
    return <RiFileEditLine />;
  if (tool.includes("dir") || tool.includes("list") || tool.includes("folder"))
    return <RiFolderLine />;
  if (tool.includes("search") || tool.includes("grep")) return <RiSearchLine />;
  if (tool.includes("read") || tool.includes("file")) return <RiFileTextLine />;
  return <RiToolsLine />;
}

/**
 * The status one tool call's row carries: the state-to-status mapping
 * from the Tool pattern (ui.shadcn.com/docs/ai-elements/aria/tool),
 * shared by every row shape so a plain tool line and a subagent row
 * read the same states the same way.
 *
 * @param props - The call's raw state string and the streaming flag
 * @returns The row's status
 */
function callStatus(state: string, isAnimating?: boolean) {
  // Denied is a plain row: the title says so, no status needed.
  if (state === "output-denied") return undefined;
  if (state.includes("error")) return "error" as const;
  // A pending approval is not a step the agent took; the buttons live in
  // the turn's approval surface, so the line only marks the wait.
  if (state === "approval-requested") return "pending" as const;
  if (state === "output-available") return undefined;
  // In flight: running while the turn streams. A call whose output has
  // not landed after the turn stopped is waiting on something outside
  // the stream — pending work, not a failure.
  return isAnimating ? ("running" as const) : ("pending" as const);
}

/**
 * Which specialist a delegation-shaped call ran, for the subagent row's
 * title. A live task names the agent directly; `start_specialist` names
 * it in its input arguments; once settled, the tool name is the best
 * witness left.
 *
 * @param props - The tool name, the call's raw input, and the live task
 * @returns The agent's name as the row's title reads it
 */
function agentLabel(
  tool: string,
  input: string | undefined,
  task?: DelegatedTaskInCard,
) {
  if (task && task.agentName) return task.agentName;
  // start_specialist's arguments carry the agent by name.
  if (tool === "start_specialist" && input) {
    try {
      const parsed: unknown = JSON.parse(input);
      if (parsed && typeof parsed === "object") {
        const agent = (parsed as { agent?: unknown }).agent;
        if (typeof agent === "string" && agent.trim() !== "") return agent;
      }
    } catch {
      // A malformed input falls through to the tool-name mapping.
    }
  }
  if (tool === "implement_task") return "implementation";
  if (tool === "plan_task") return "planner";
  if (tool === "delegate_task") return "delegate";
  if (tool === "start_specialist") return "specialist";
  return tool.replace(/_task$/, "").replace(/_/g, " ");
}

/**
 * Whether a call launches a specialist and therefore reads as a
 * subagent row rather than a plain tool line. A run whose parts streamed
 * back as children is one case; `start_specialist` is the other — the
 * specialist runs as its own durable run, and its row names it.
 *
 * @param props - The tool call
 * @returns True when the row should follow the Subagent pattern
 */
function isSpecialistCall(call: MessageToolCall) {
  return Boolean(call.children) || call.tool === "start_specialist";
}

/**
 * How one tool call reads on its line: the state-to-status and
 * state-to-title mapping from the Tool pattern. Status is carried by
 * the title's wording as well as its color, so the state is legible
 * without relying on color.
 *
 * @param props - The call and whether the turn still streams
 * @returns The line's status and title
 */
function callPresentation(call: MessageToolCall, isAnimating?: boolean) {
  const state = call.state ?? "";
  const status = callStatus(state, isAnimating);
  if (status === "error") {
    return { status, title: `Failed to run ${call.tool}` };
  }
  if (state === "output-denied") {
    return { status, title: `Denied ${call.tool}` };
  }
  if (state === "approval-requested") {
    return { status, title: `Waiting for approval: ${call.tool}` };
  }
  if (state === "output-available") {
    return { status, title: `Ran ${call.tool}` };
  }
  if (status === "running") {
    return { status, title: `Running ${call.tool}` };
  }
  return { status, title: `Waiting for ${call.tool}` };
}

/**
 * One tool call as a Trace row, per the Tool pattern: a plain row while
 * the call runs, a collapsible row — output in a code block — once its
 * output lands, and a plain "Denied" row when it was refused.
 *
 * @param props - The call, the streaming flag, and the plugin tool set
 * @returns The call's Trace row
 */
function ToolLine({
  call,
  isAnimating,
  pluginTools}: {
  call: MessageToolCall;
  /** Whether the turn is still streaming (drives the running state). */
  isAnimating?: boolean;
  /** Tool names that belong to a plugin surface (drives the icon). */
  pluginTools: ReadonlySet<string>;
}) {
  const isPlugin = pluginTools.has(call.tool);
  const { status, title } = callPresentation(call, isAnimating);
  // The input arguments are the row's description: one line, so the row
  // keeps its shape and the full body still opens with the output.
  const summary = (call.input ?? "").replace(/\s+/g, " ").trim();
  const line = (
    <TraceLine status={status}>
      <TraceIcon>
        <ToolLineIcon isPlugin={isPlugin} tool={call.tool} />
      </TraceIcon>
      <TraceTitle>{title}</TraceTitle>
      {summary !== "" && (
        <TraceDescription>
          {summary.length > 80 ? `${summary.slice(0, 80)}…` : summary}
        </TraceDescription>
      )}
    </TraceLine>
  );
  const detail = (call.output ?? "").trim();
  // Nothing to open yet: the row is the whole component.
  if (detail === "") return line;
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <CodeBlock size="sm">
          <CodeBlockContent wrap className="max-h-64">
            {detail}
          </CodeBlockContent>
        </CodeBlock>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * The door to a specialist's own session, for a launch whose work did
 * not stream back into this call: the tool's output carries the run id
 * the session page is keyed on. Without one (an expired or failed
 * launch) the row says so plainly rather than linking nowhere.
 *
 * @param props - The launch call
 * @returns The link, or the plain note
 */
function SpecialistSessionLink({ call }: { call: MessageToolCall }) {
  let runId: string | undefined;
  if (call.output) {
    try {
      const parsed: unknown = JSON.parse(call.output);
      if (parsed && typeof parsed === "object") {
        const candidate =
          (parsed as { runId?: unknown }).runId ??
          (parsed as { run_id?: unknown }).run_id ??
          (parsed as { id?: unknown }).id;
        if (typeof candidate === "string" && candidate.trim() !== "") {
          runId = candidate;
        }
      }
    } catch {
      // A prose output carries no run id; the note below stands.
    }
  }
  if (runId) {
    return (
      <Link
        className="text-accent hover:underline"
        href={`/specialist/${encodeURIComponent(runId)}`}
      >
        Its work lives in the specialist&rsquo;s own session — open it →
      </Link>
    );
  }
  return <span>Its work lives in the specialist&rsquo;s own session.</span>;
}

/**
 * A delegated specialist's run as a subagent row, per the Subagent
 * pattern (ui.shadcn.com/docs/ai-elements/aria/subagent): the row reads
 * "Running the implementation agent" while it works and "Ran the
 * implementation agent" once it has, and opens into the specialist's
 * own tool calls and what it found. It stays open while the run is
 * live, and the reader's click wins after that.
 *
 * @param props - The delegated call, the streaming flag, the
 *   delegated-approval handler, and the plugin tool set
 * @returns The subagent's Trace row
 */
function SubagentRow({
  call,
  isAnimating,
  onResolveDelegatedApproval,
  pluginTools}: {
  call: MessageToolCall;
  /** Whether the turn is still streaming. */
  isAnimating?: boolean;
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
  /** Tool names that belong to a plugin surface. */
  pluginTools: ReadonlySet<string>;
}) {
  const [open, setOpen] = useState<boolean | undefined>(undefined);
  const status = callStatus(call.state ?? "", isAnimating);
  const running = status === "running";
  const agent = agentLabel(call.tool, call.input, call.delegatedTask);
  // The task the specialist was given, one line, as the row's
  // description; the full body opens with the run's detail.
  const task = (call.input ?? "").replace(/\s+/g, " ").trim();
  const title =
    status === "error"
      ? `Failed to run the ${agent} agent`
      : running
        ? `Running the ${agent} agent`
        : status === "pending"
          ? `Waiting for the ${agent} agent`
          : `Ran the ${agent} agent`;
  const line = (
    <TraceLine status={status}>
      <TraceIcon>
        {status === "error" ? <RiErrorWarningLine /> : <RiRobotLine />}
      </TraceIcon>
      <TraceTitle>{title}</TraceTitle>
      {task !== "" && (
        <TraceDescription>
          {task.length > 80 ? `${task.slice(0, 80)}…` : task}
        </TraceDescription>
      )}
    </TraceLine>
  );
  return (
    <TraceCollapsible isExpanded={open ?? running} onExpandedChange={setOpen}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="flex flex-col gap-2">
        {call.children ? (
          <SubagentWork
            isAnimating={isAnimating}
            parts={call.children}
            pluginTools={pluginTools}
            onResolveDelegatedApproval={onResolveDelegatedApproval}
          />
        ) : (
          /* No streamed work under this call: the specialist runs as
             its own durable session, so the row offers the door to it
             rather than an empty panel. */
          <div className="text-xs text-muted-foreground">
            <SpecialistSessionLink call={call} />
          </div>
        )}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * One turn's tool calls, grouped under a single summary row — the Chain
 * of Thought pattern (ui.shadcn.com/docs/ai-elements/aria/chain-of-thought):
 * the summary says what happened ("4 tool calls", any failures counted),
 * and the per-call rows sit inside it, so a working turn reads as one
 * line until the reader opens it. It opens while the turn streamss and
 * closes when it ends, unless the reader chooses otherwise. A single
 * call skips the summary: one step is already one row.
 *
 * @param props - The calls, the streaming flag, the delegated-approval
 *   handler, and the plugin tool set
 * @returns The grouped rows
 */
function ToolTraceGroup({
  calls,
  isAnimating,
  onResolveDelegatedApproval,
  pluginTools}: {
  calls: NonNullable<ChatMessage["toolCalls"]>;
  /** Whether the turn is still streaming. */
  isAnimating?: boolean;
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
  /** Tool names that belong to a plugin surface. */
  pluginTools: ReadonlySet<string>;
}) {
  const [open, setOpen] = useState<boolean | undefined>(undefined);
  const running = Boolean(isAnimating);
  const failed = calls.filter((c) => (c.state ?? "").includes("error")).length;
  if (calls.length <= 1) {
    return (
      <ToolTrace
        calls={calls}
        isAnimating={isAnimating}
        pluginTools={pluginTools}
        onResolveDelegatedApproval={onResolveDelegatedApproval}
      />
    );
  }
  const count = `${calls.length} tool call${calls.length === 1 ? "" : "s"}`;
  const line = (
    <TraceLine status={running ? "running" : failed > 0 ? "error" : undefined}>
      <TraceIcon>
        {running ? (
          <RiLoaderLine className="animate-spin" />
        ) : failed > 0 ? (
          <RiErrorWarningLine />
        ) : (
          <RiToolsLine />
        )}
      </TraceIcon>
      <TraceTitle>{running ? `Working — ${count}` : count}</TraceTitle>
      {failed > 0 && <TraceDescription>{failed} failed</TraceDescription>}
    </TraceLine>
  );
  return (
    <TraceCollapsible isExpanded={open ?? running} onExpandedChange={setOpen}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <ToolTrace
          calls={calls}
          isAnimating={isAnimating}
          pluginTools={pluginTools}
          onResolveDelegatedApproval={onResolveDelegatedApproval}
        />
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * One turn's tool calls as a list of Trace rows. Calls the backend split
 * across several protocol messages arrive already merged by the caller,
 * so this is the whole list — no group header to duplicate the per-row
 * titles.
 *
 * @param props - The calls, the streaming flag, the delegated-approval
 *   handler, and the plugin tool set
 * @returns The turn's tool-call rows
 */
function ToolTrace({
  calls,
  isAnimating,
  onResolveDelegatedApproval,
  pluginTools}: {
  calls: NonNullable<ChatMessage["toolCalls"]>;
  /** Whether the turn is still streaming. */
  isAnimating?: boolean;
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
  /** Tool names that belong to a plugin surface. */
  pluginTools: ReadonlySet<string>;
}) {
  return (
    <Trace className="mt-1.5">
      {calls.map((call, callIdx) => (
        <div
          key={`tool-${callIdx}-${call.tool}-${call.toolCallId ?? ""}`}
          className="flex flex-col gap-1"
        >
          {/* A delegated specialist's run reads as a subagent row whose
              content IS its streamed work — the text and tool calls
              nested inside the call they ran under, not beside it. */}
          {isSpecialistCall(call) ? (
            <SubagentRow
              call={call}
              isAnimating={isAnimating}
              pluginTools={pluginTools}
              onResolveDelegatedApproval={onResolveDelegatedApproval}
            />
          ) : (
            <ToolLine
              call={call}
              isAnimating={isAnimating}
              pluginTools={pluginTools}
            />
          )}
          {/* Steering and stopping that task, while it is still running:
              the controls sit with the work they act on, not the chrome. */}
          {call.delegatedTask && (
            <DelegationTaskControls task={call.delegatedTask} />
          )}
        </div>
      ))}
    </Trace>
  );
} /**
 * One subagent's streamed work, rendered under the tool call it ran in.
 *
 * The relay brackets a delegated run so these parts can be attributed to
 * that call; this is what makes a delegate inspectable - the implementer's
 * own file reads, writes and text, inside the `implement_task` card.
 */
function SubagentWork({
  parts,
  isAnimating,
  onResolveDelegatedApproval,
  pluginTools}: {
  /** The specialist's streamed work, when any came back. A specialist
      run whose parts never streamed into this call (it runs as its own
      durable run) has none, and only the parent row's output shows. */
  parts?: MessageParts;
  /** Whether the turn is still streaming (thinking shown open by default). */
  isAnimating?: boolean;
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
  /** Tool names that belong to a plugin surface. */
  pluginTools: ReadonlySet<string>;
}) {
  return (
    <div
      aria-label="Work done inside this tool call"
      className="flex flex-col gap-2"
      role="group"
    >
      {parts?.reasoning && (
        <ReasoningLine isAnimating={isAnimating} text={parts.reasoning} />
      )}
      {parts?.text && (
        <div className="text-xs text-muted-foreground">
          <MarkdownRenderer content={parts.text} isAnimating={isAnimating} />
        </div>
      )}
      {parts?.toolCalls && parts.toolCalls.length > 0 && (
        <ToolTrace
          calls={parts.toolCalls}
          isAnimating={isAnimating}
          pluginTools={pluginTools}
        />
      )}
      {/* A delegated task's gated write, decided in place. It sits
                with the work it belongs to rather than in the run's
                approval batch, which cannot answer it. */}
      {onResolveDelegatedApproval &&
        (parts?.toolCalls ?? [])
          .filter((c) => c.state === "approval-requested")
          .filter((c) => Boolean(c.toolCallId))
          .map((call) => (
            /* A waiting approval is a question for the person, not a
                step the agent took, so it sits as an Item with the
                Approve/Reject actions beside it — never a Trace row
                (ui.shadcn.com/docs/ai-elements/aria/tool#approval). */
            <Item
              key={`delegated-approval-${call.toolCallId}`}
              size="sm"
              variant="outline"
            >
              <ItemMedia variant="icon">
                <RiErrorWarningLine />
              </ItemMedia>
              <ItemContent>
                <ItemTitle>
                  ⏳ {call.tool} needs your approval
                  {call.input ? ` (${call.input})` : ""}
                </ItemTitle>
              </ItemContent>
              <ItemActions>
                <Button
                  isDisabled={false}
                  size="sm"
                  variant="primary"
                  onPress={() =>
                    onResolveDelegatedApproval(call.toolCallId as string, true)
                  }
                >
                  ✅ Approve
                </Button>
                <Button
                  isDisabled={false}
                  size="sm"
                  variant="secondary"
                  onPress={() =>
                    onResolveDelegatedApproval(call.toolCallId as string, false)
                  }
                >
                  ❌ Reject
                </Button>
              </ItemActions>
            </Item>
          ))}
    </div>
  );
}

/**
 * MessageList component.
 * Renders conversation transcript messages with Markdown rendering.
 *
 * @param props - Component properties
 * @returns JSX element rendering the messages list
 */
export function MessageList({
  history = [],
  isAnimating,
  onResolveDelegatedApproval}: MessageListProps) {
  const pluginTools = usePluginToolNames();

  /**
   * Merge consecutive assistant messages into one display group so that
   * tool calls the backend split across several protocol messages render
   * under a single header instead of one block per call. The merge is
   * display-only: message ids, tool-call ids and approval state are kept
   * per-call so HITL / delegation handling is untouched.
   */
  const groups = useMemo(() => {
    const out: Array<{ kind: "single" | "group"; messages: ChatMessage[] }> =
      [];
    let cur: ChatMessage[] | null = null;
    const push = (buf: ChatMessage[]) => {
      if (buf.length === 0) return;
      if (buf.length === 1) out.push({ kind: "single", messages: buf });
      else out.push({ kind: "group", messages: buf });
    };
    for (const msg of history) {
      if (msg.role === "assistant") {
        if (cur === null) cur = [msg];
        else cur.push(msg);
      } else {
        push(cur ?? []);
        cur = null;
        out.push({ kind: "single", messages: [msg] });
      }
    }
    push(cur ?? []);
    return out;
  }, [history]);

  return (
    <div
      aria-label="Conversation transcript"
      className="message-list flex flex-col gap-2"
      role="log"
    >
      {groups.map((g, gi) => {
        const assistant =
          g.kind === "group"
            ? g.messages
            : g.messages[0].role === "assistant"
              ? g.messages
              : null;
        const isGroup = g.kind === "group" && !!assistant;
        const role = isGroup ? "assistant" : g.messages[0].role;
        const roleLabel =
          role === "user" ? "User" : role === "system" ? "System" : "Agent";
        const text = assistant
          ? assistant
              .map((m) => m.content)
              .filter(Boolean)
              .join("\n")
          : g.messages[0].content;
        const reasoning = assistant
          ? assistant
              .map((m) => m.reasoning)
              .filter(Boolean)
              .join("\n")
          : g.messages[0].reasoning;
        const toolCalls = isGroup
          ? ([] as ChatMessage["toolCalls"]).concat(
              ...g.messages.map((m) => m.toolCalls ?? []),
            )
          : g.messages[0].toolCalls;
        return (
          <Message
            key={`msg-${gi}-${isGroup ? "group" : (g.messages[0].id ?? gi)}`}
            align={role === "user" ? "end" : "start"}
            className="message-list-item"
          >
            {/* The role reads as an avatar plus the header label - the
                Message pattern's frame, the same on every surface. */}
            <MessageAvatar aria-hidden="true">
              {role === "user" ? (
                <RiUserLine />
              ) : role === "system" ? (
                <RiSparklingLine />
              ) : (
                <RiRobotLine />
              )}
            </MessageAvatar>
            <MessageContent>
              <MessageHeader>{roleLabel}</MessageHeader>
              {reasoning && (
                <ReasoningLine isAnimating={isAnimating} text={reasoning} />
              )}
              <MarkdownRenderer
                content={text}
                isAnimating={role === "assistant" && isAnimating}
              />
              {toolCalls && toolCalls.length > 0 && (
                <ToolTraceGroup
                  calls={toolCalls}
                  isAnimating={isAnimating}
                  pluginTools={pluginTools}
                  onResolveDelegatedApproval={onResolveDelegatedApproval}
                />
              )}
            </MessageContent>
          </Message>
        );
      })}
    </div>
  );
}

export default MessageList;
