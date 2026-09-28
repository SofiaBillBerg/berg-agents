/**
 * AI SDK integration hook for the harness.
 * Bridges the harness event stream with AI SDK's useChat for real-time streaming.
 */

import { useCallback, useEffect, useState } from 'react';

import type { HarnessEvent } from './webhook';
import { useHarness } from './harness-provider';
import { eventToAISDKPart, createHarnessEncoder } from './ai-sdk-streaming';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  parts?: Array<Record<string, unknown>>;
}

export function useAISDKChat() {
  const { harness, isConnected } = useHarness();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!harness) return;

    const handleEvent = (event: HarnessEvent) => {
      const part = eventToAISDKPart(event);
      if (!part) return;

      setMessages((prev) => {
        const newMessages = [...prev];
        switch (part.type) {
          case 'messageStart': {
            const msgId = part.data.messageId as string;
            if (!newMessages.find((m) => m.id === msgId)) {
              newMessages.push({ id: msgId, role: 'assistant', content: '', parts: [] });
            }
            setIsStreaming(true);
            break;
          }
          case 'textDelta': {
            const msgId = part.data.messageId as string;
            const lastMsg = newMessages[newMessages.length - 1];
            if (lastMsg && lastMsg.id === msgId && lastMsg.role === 'assistant') {
              lastMsg.content += part.data.delta as string;
            } else {
              newMessages.push({ id: msgId, role: 'assistant', content: part.data.delta as string, parts: [] });
            }
            break;
          }
          case 'error': {
            setError(part.data.message as string);
            setIsStreaming(false);
            break;
          }
          case 'finish': {
            setIsStreaming(false);
            break;
          }
          default:
            break;
        }
        return newMessages;
      });
    };

    const unsubscribe = harness.subscribeToEvents(handleEvent);
    const existingEvents = harness.getCurrentEvents();
    existingEvents.forEach(handleEvent);

    return () => unsubscribe();
  }, [harness]);

  const sendMessage = useCallback(async (content: string, taskType: string = 'generic') => {
    if (!harness) throw new Error('Harness not connected');

    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, role: 'user', content }]);
    setIsStreaming(true);
    setError(null);

    try {
      await harness.executeTask(content, taskType);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Task execution failed';
      setError(msg);
      setIsStreaming(false);
      setMessages((prev) => [...prev, { id: `error-${Date.now()}`, role: 'assistant', content: `Error: ${msg}` }]);
    }
  }, [harness]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  const stop = useCallback(() => {
    if (harness?.reconnect) harness.reconnect();
    setIsStreaming(false);
  }, [harness]);

  return { messages, isStreaming, error, isConnected, sendMessage, clearMessages, stop };
}