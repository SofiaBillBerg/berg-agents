import React from "react";

import { Alert, Card, Chip, Spinner, Surface } from "@heroui/react";

import { MessageList } from "./MessageList.tsx";

export interface ChatTranscriptProps {
  transcript: Array<{ role: string; content: string }>;
  isExecuting: boolean;
  hitlRequest: unknown;
  onExport?: () => void;
}

/**
 * ChatTranscript — HeroUI v3 enhanced conversation display.
 * Uses Alert with compound components for HITL notifications and
 * Card compound components for structure.
 */
export function ChatTranscript({
  transcript,
  isExecuting,
  hitlRequest,
  onExport,
}: ChatTranscriptProps) {
  return (
    <>
      <Card className="mb-4" variant="default">
        <Card.Content className="p-2">
          <div className="conversation-container overflow-y-auto flex-1 min-h-0">
            <MessageList history={transcript} />

            {/* HITL Pending Notice — HeroUI v3 Alert with compound components */}
            {hitlRequest != null && (
              <Alert className="mt-3" status="warning">
                <Alert.Indicator />
                <Alert.Title>
                  ⏸️ Waiting for your approval
                </Alert.Title>
                <Alert.Description>
                  A task is pending your review above. Please check the HITL
                  surface below to approve, reject, or edit the proposed action.
                </Alert.Description>
              </Alert>
            )}
          </div>
        </Card.Content>
      </Card>

      {/* Thinking Bubble — HeroUI v3 Spinner + Surface */}
      {isExecuting && !hitlRequest && (
        <Surface
          className="thinking-bubble p-3 mb-4 flex items-center gap-2"
          variant="secondary"
        >
          <Spinner color="accent" size="sm" />
          <span className="text-sm">Thinking...</span>
        </Surface>
      )}
    </>
  );
}

export default ChatTranscript;