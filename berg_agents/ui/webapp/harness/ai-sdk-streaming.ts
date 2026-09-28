/**
 * AI SDK streaming integration for the harness.
 * Bridges SSE events from the Python backend to the AI SDK's useChat hook.
 */

import type { UIMessage } from '@ai-sdk/react';

import type { HarnessEvent, TaskResult } from './webhook';

/** SSE event type mapping for AI SDK UI message stream protocol */
type AISDKEvent =
  | { type: 'messageStart'; data: { messageId: string } }
  | { type: 'textDelta'; data: { messageId: string; delta: string } }
  | { type: 'messageEnd'; data: { messageId: string } }
  | { type: 'dataBlock'; data: { data: string; messageId?: string } }
  | { type: 'error'; data: { message: string } }
  | { type: 'finish'; data: { totalTokens?: number; usage?: Record<string, unknown> } }
  | { type: string; data: Record<string, unknown> };

/** Convert internal HarnessEvent to AI SDK UI message stream part */
export function eventToAISDKPart(event: HarnessEvent): {
  type: string;
  data: Record<string, unknown>;
} | null {
  const { type, data } = event;

  switch (type) {
    case 'task_started':
      return {
        type: 'messageStart',
        data: { messageId: `msg-${Date.now()}`, role: 'assistant' },
      };

    case 'task_completed': {
      const result = data as TaskResult;
      if (result?.implementation?.answer) {
        return {
          type: 'textDelta',
          data: { messageId: `msg-${Date.now()}`, delta: result.implementation.answer },
        };
      }
      return { type: 'messageEnd', data: { messageId: `msg-${Date.now()}` } };
    }

    case 'task_failed':
      return {
        type: 'error',
        data: { message: (data as Record<string, unknown>)?.error || 'Task failed' },
      };

    case 'data-hitl-requested':
      return {
        type: 'dataBlock',
        data: {
          data: JSON.stringify({ type: 'hitl', ...(data as Record<string, unknown>) }),
          messageId: `msg-${Date.now()}`,
        },
      };

    case 'data-task-completed':
      return {
        type: 'finish',
        data: { totalTokens: 0, usage: {} },
      };

    case 'subagent_start':
      return {
        type: 'toolCallStart',
        data: {
          toolCallId: `tool-${Date.now()}`,
          toolName: (data as Record<string, unknown>)?.name || 'subagent',
          input: data as Record<string, unknown>,
        },
      };

    default:
      // Pass through as data block for unhandled event types
      return {
        type: 'dataBlock',
        data: {
          data: JSON.stringify(event),
          messageId: `msg-${Date.now()}`,
        },
      };
  }
}

/** Convert harness events to AI SDK messages */
export function eventsToMessages(events: HarnessEvent[]): UIMessage[] {
  const messages: UIMessage[] = [];

  for (const event of events) {
    const part = eventToAISDKPart(event);
    if (!part) continue;

    if (part.type === 'textDelta') {
      const lastMsg = messages[messages.length - 1];
      if (lastMsg && lastMsg.role === 'assistant') {
        // In v7, content is accessed via parts or a type-safe accessor
        // Cast to mutable form for append
        const msg = lastMsg as unknown as { content: string };
        if (msg.content) {
          msg.content += (part.data.delta as string);
        }
      } else {
        messages.push({
          id: part.data.messageId as string,
          role: 'assistant',
          content: part.data.delta as string,
          parts: [],
        } as unknown as UIMessage);
      }
    }

    if (part.type === 'messageStart') {
      const msgId = part.data.messageId as string;
      if (!messages.find((m) => m.id === msgId)) {
        messages.push({
          id: msgId,
          role: 'assistant',
          content: '',
          parts: [],
        } as unknown as UIMessage);
      }
    }
  }

  return messages;
}

/** Create an encoder that bridges harness events to AI SDK format */
export function createHarnessEncoder() {
  return (event: HarnessEvent): string | null => {
    const part = eventToAISDKPart(event);
    if (!part) return null;
    return `data: ${JSON.stringify(part)}\n\n`;
  };
}

export type { AISDKEvent };