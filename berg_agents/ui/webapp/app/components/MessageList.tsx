import { useState } from "react";
import { Surface } from "@heroui/react";

import { MarkdownRenderer } from "./MarkdownRenderer.tsx";
import { ToolCard } from "./ToolCard.tsx";

export interface MessageToolCall {
  tool: string;
  input?: string;
  output?: string;
  state?: string;
}

export interface MessageItem {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  reasoning?: string;
  toolCalls?: MessageToolCall[];
}

export interface MessageListProps {
  history?: MessageItem[];
}

/**
 * Collapsible reasoning trace for one assistant message.
 * The model's chain-of-thought streams in as `reasoning` parts;
 * shown collapsed by default so long traces don't flood the chat.
 */
function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="reasoning-block mt-1">
      <button
        aria-label={open ? "Hide reasoning" : "Show reasoning"}
        className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? "🧠 Hide thinking" : "🧠 Show thinking"}
      </button>
      {open && (
        <div className="mt-1 border-l-2 border-accent/40 pl-2 text-xs text-muted-foreground">
          <MarkdownRenderer content={text} />
        </div>
      )}
    </div>
  );
}

/**
 * One assistant turn's tool calls as a single collapsible group.
 * A lone call or two stays open so progress reads inline; a longer
 * batch starts collapsed so the answer above it stays followable.
 * Each call keeps its own Show/Hide + Copy inside.
 */
function ToolCallGroup({
  calls}: {
  calls: NonNullable<MessageItem["toolCalls"]>;
}) {
  const [open, setOpen] = useState(calls.length <= 3);
  return (
    <div className="mt-1.5 flex flex-col gap-1 rounded-md border border-border px-1.5 py-1">
      <button
        aria-label={
          open
            ? `Collapse ${calls.length} tool calls`
            : `Expand ${calls.length} tool calls`
        }
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
        onClick={() => setOpen((prev) => !prev)}
        type="button"
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="font-mono">
          🔧 {calls.length} tool call{calls.length === 1 ? "" : "s"}
        </span>
        <span className="truncate text-[11px]">
          {calls.map((c) => c.tool).join(", ")}
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-1">
          {calls.map((call, callIdx) => (
            <ToolCard
              key={`tool-${callIdx}-${call.tool}`}
              tool={call.tool}
              input={call.input}
              output={call.output}
              expanded={false}
              state={call.state}
            />
          ))}
        </div>
      )}
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
export function MessageList({ history = [] }: MessageListProps) {
  return (
    <div
      aria-label="Conversation transcript"
      className="message-list flex flex-col gap-2"
      role="log"
    >
      {history.map((msg, idx) => {
        const roleClass =
          msg.role === "user"
            ? "message-role-user"
            : msg.role === "system"
              ? "message-role-system"
              : "message-role-agent";
        const roleLabel =
          msg.role === "user"
            ? "User"
            : msg.role === "system"
              ? "System"
              : "Agent";
        const text = msg.content || msg.text || "";
        return (
          <Surface
            key={msg.id || `msg-${idx}`}
            className={`message-list-item px-2.5 py-2 ${roleClass}`}
            variant="secondary"
          >
            <div className="text-xs font-semibold tracking-wide uppercase text-muted mb-1">
              {roleLabel}
            </div>
            {msg.reasoning && <ReasoningBlock text={msg.reasoning} />}
            <div className="message-list-content text-sm">
              <MarkdownRenderer content={text} />
            </div>
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <ToolCallGroup calls={msg.toolCalls} />
            )}
          </Surface>
        );
      })}
    </div>
  );
}

export default MessageList;
