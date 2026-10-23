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

import React, {useEffect, useRef} from "react";
import {Alert, Card, Spinner, Surface} from "@heroui/react";

import {MessageList} from "./MessageList.tsx";
import {ToolCard} from "./ToolCard";

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
  /** Raw input arguments (JSON-serialized string) - optional */
  input?: string;
  /** Output from the tool - must be JSON-serializable */
  output?: any;
  /** Whether the card is currently expanded */
  expanded?: boolean;
  /** Callback to toggle expansion */
  onToggle?: () => void;
}

/** DOM id of the transcript scroll region (jump buttons target it). */
export const CHAT_SCROLL_ID = "chat-scroll";

export function ChatTranscript({
  transcript,
  isExecuting,
  hitlRequest,
  onExport,
  toolResults}: ChatTranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Stick-to-bottom while new content streams in — but only when the
  // user is already near the bottom, so reading back through history
  // is never yanked away.
  const lastCount = useRef(transcript.length);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (transcript.length !== lastCount.current) {
      lastCount.current = transcript.length;
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      if (nearBottom) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [transcript]);

  return (
    <>
      <Card className="mb-2 min-h-0 flex-1 flex flex-col" variant="default">
        <Card.Content className="p-1.5 min-h-0 flex-1 flex flex-col">
          <div
            ref={scrollRef}
            id={CHAT_SCROLL_ID}
            className="conversation-container"
          >
            <MessageList history={transcript} />

            {/* HITL Pending Notice - HeroUI Alert with compound components */}
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

      {/* Thinking Bubble - HeroUI Spinner + Surface */}
      {isExecuting && !hitlRequest && (
        <Surface
          className="thinking-bubble p-3 mb-4 flex items-center gap-2"
          variant="secondary"
        >
          <Spinner color="accent" size="sm" />
          <span className="text-sm">Thinking...</span>
        </Surface>
      )}

      {/* Tool Result Cards - rendered below the thinking bubble */}
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
