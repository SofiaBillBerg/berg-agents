import React from "react";

import { Alert, Card, Spinner, Surface } from "@heroui/react";

import { MessageList } from "./MessageList.tsx";
import { ToolCard } from "./ToolCard";

export interface ChatTranscriptProps {
  transcript: Array<{ role: string; content: string }>;
  isExecuting: boolean;
  hitlRequest: unknown;
  onExport?: () => void;
  /** Optional tool results to display as collapsible cards */
  toolResults?: ToolResult[];
}

/** Minimal description of a tool result for rendering */
export interface ToolResult {
  /** Name of the tool (e.g. "read_file", "run_task") */
  tool: string;
  /** Raw input arguments (JSON‑serialised string) – optional */
  input?: string;
  /** Output from the tool – must be JSON‑serialisable */
  output?: any;
  /** Whether the card is currently expanded */
  expanded?: boolean;
  /** Callback to toggle expansion */
  onToggle?: () => void;
}

export function ChatTranscript({
  transcript,
  isExecuting,
  hitlRequest,
  onExport,
  toolResults}: ChatTranscriptProps) {
  return (
    <>
      <Card className="mb-4" variant="default">
        <Card.Content className="p-2">
          <div className="conversation-container overflow-y-auto flex-1 min-h-0 max-h-[55vh]">
            <MessageList history={transcript} />

            {/* HITL Pending Notice – HeroUI Alert with compound components */}
            {hitlRequest != null && (
              <Alert className="mt-3" status="warning">
                <Alert.Indicator />
                <Alert.Title>⏸️ Waiting for your approval</Alert.Title>
                <Alert.Description>
                  A task is pending your review above. Please check the HITL
                  surface below to approve, reject, or edit the proposed action.
                </Alert.Description>
              </Alert>
            )}
          </div>
        </Card.Content>
      </Card>

      {/* Thinking Bubble – HeroUI Spinner + Surface */}
      {isExecuting && !hitlRequest && (
        <Surface
          className="thinking-bubble p-3 mb-4 flex items-center gap-2"
          variant="secondary"
        >
          <Spinner color="accent" size="sm" />
          <span className="text-sm">Thinking...</span>
        </Surface>
      )}

      {/* Tool Result Cards – rendered below the thinking bubble */}
      {toolResults && toolResults.length > 0 && (
        <div className="mt-4 space-y-3">
          {toolResults.map((tr, idx) => (
            <ToolCard key={idx} {...tr} onToggle={tr.onToggle} />
          ))}
        </div>
      )}
    </>
  );
}

export default ChatTranscript;
