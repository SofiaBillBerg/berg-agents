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

import type { ChatMessage } from "@/harness";

import React, { useEffect, useRef, useState } from "react";
import { Alert, Card, Spinner, Surface } from "@heroui/react";

import { ToolCard } from "./ToolCard";
import { MessageList } from "./MessageList.tsx";
// Import KaTeX styles for math rendering
import "katex/dist/katex.min.css";

export interface ChatTranscriptProps {
  transcript: ChatMessage[];
  isExecuting: boolean;
  hitlRequest: unknown;
  onExport?: () => void;
  /** Whether the assistant turn is currently streaming (animates code blocks). */
  isAnimating?: boolean;
  /** Answer a delegated task's gated write from its own card. */
  onResolveDelegatedApproval?: (callId: string, approved: boolean) => void;
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
  output?: unknown;
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
  isAnimating,
  hitlRequest,
  onExport,
  toolResults,
  onResolveDelegatedApproval}: ChatTranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Follow the bottom while new content streams in. When auto-scroll is on the
  // transcript always sticks to the latest message so the user can read the
  // agent's reasoning and output as it lands without scrolling manually. When
  // off the viewport stays where the user left it.
  const [autoScroll, setAutoScroll] = useState(true);
  const lastCount = useRef(transcript.length);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !autoScroll) return;
    if (transcript.length !== lastCount.current) {
      lastCount.current = transcript.length;
      el.scrollTop = el.scrollHeight;
    }
  }, [transcript, autoScroll]);

  return (
    <>
      <Card className="mb-2 min-h-0 flex-1 flex flex-col" variant="default">
        <Card.Content className="p-1.5 min-h-0 flex-1 flex flex-col">
          {/* Auto-scroll toggle - stays with the transcript so the user can
              follow streaming output or pin the viewport to read back. */}
          <div className="flex items-center gap-1.5 mb-0.5">
            <button
              aria-label={
                autoScroll ? "Disable auto-scroll" : "Enable auto-scroll"
              }
              className="rounded-md border border-border bg-background px-2 py-0.5 text-xs"
              type="button"
              onClick={() => setAutoScroll((prev) => !prev)}
            >
              {autoScroll ? "⏬ Autoscroll ON" : "⏸ Autoscroll OFF"}
            </button>
            <span className="text-[10px] text-muted-foreground">
              {autoScroll ? "following new messages" : "viewport pinned"}
            </span>
          </div>
          <div
            ref={scrollRef}
            className="conversation-container"
            id={CHAT_SCROLL_ID}
          >
            <MessageList
              history={transcript}
              isAnimating={isAnimating}
              onResolveDelegatedApproval={onResolveDelegatedApproval}
            />

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
