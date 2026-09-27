import React from "react";

import { MessageList } from "./MessageList.tsx";

export interface ChatTranscriptProps {
  transcript: Array<{ role: string; content: string }>;
  isExecuting: boolean;
  hitlRequest: unknown;
  onExport?: () => void;
}

/**
 * ChatTranscript — extracted from App.tsx 865L god-file.
 * Single owner for the conversation history + thinking bubble + HITL prompt.
 */
export function ChatTranscript({
  transcript,
  isExecuting,
  hitlRequest,
  onExport,
}: ChatTranscriptProps) {
  return (
    <>
      <div className="conversation-container overflow-y-auto flex-1 min-h-0 p-2">
        <MessageList history={transcript} />
        {hitlRequest != null && (
          <div className="hitl-pending-notice mt-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
            <p className="text-sm font-semibold text-yellow-600 dark:text-yellow-400">
              ⏸️ Waiting for your approval — a task is pending review above.
            </p>
          </div>
        )}
      </div>
      {isExecuting && !hitlRequest && (
        <div className="thinking-bubble">
          <div className="thinking-content">
            <span className="spinner">⟳</span> Thinking...
          </div>
        </div>
      )}
    </>
  );
}

export default ChatTranscript;
