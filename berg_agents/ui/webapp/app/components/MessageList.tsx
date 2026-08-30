import React from "react";
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
 * Renders conversation transcript messages with markdown rendering.
 *
 * @param props - Component properties
 * @returns JSX element rendering the messages list
 */
export function MessageList({ history = [] }: MessageListProps) {
  return (
    <div className="message-list flex flex-col gap-3">
      {history.map((msg, idx) => {
        const text = msg.content || msg.text || "";
        return (
          <div
            key={msg.id || `msg-${idx}`}
            className="message-list-item p-3 bg-surface rounded-lg border border-border"
          >
            <div className="message-list-content text-sm text-text">
              <MarkdownRenderer content={text} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default MessageList;
