import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

/**
 * MessageList component
 * Renders the chat messages list
 */
function MessageList({ history }) {
  const messages = history.map(
    (msg: { toolCalls: string | any[] }, idx: any) => ({
      ...msg,
      hasToolCalls: msg.toolCalls?.length > 0,
    }),
  );

  return (
    <div className="message-list">
      {messages.map(
        (
          msg: { content: string | null | undefined },
          idx: React.Key | null | undefined,
        ) => (
          <div key={idx} className="message-list-item">
            <div className="message-list-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                breaks={true}
              >
                {msg.content}
              </ReactMarkdown>
            </div>
          </div>
        ),
      )}
    </div>
  );
}

export default MessageList;
