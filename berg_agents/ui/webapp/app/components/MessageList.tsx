import { Surface } from "@heroui/react";

import { MarkdownRenderer } from "./MarkdownRenderer.tsx";

export interface MessageItem {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  toolCalls?: any[];
}

export interface MessageListProps {
  history?: MessageItem[];
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
      className="message-list flex flex-col gap-3"
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
            className={`message-list-item p-3 ${roleClass}`}
            variant="secondary"
          >
            <div className="text-xs font-semibold tracking-wide uppercase text-muted mb-1">
              {roleLabel}
            </div>
            <div className="message-list-content text-sm">
              <MarkdownRenderer content={text} />
            </div>
          </Surface>
        );
      })}
    </div>
  );
}

export default MessageList;
