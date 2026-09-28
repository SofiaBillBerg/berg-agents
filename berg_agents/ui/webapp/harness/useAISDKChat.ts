/*
 * Chat hook — wraps AI SDK v7's useChat to talk to the streaming backend.
 *
 * The backend (/api/chat/stream) uses pydantic_ai's VercelAIAdapter to emit
 * native Vercel AI protocol SSE. This hook provides a clean interface for
 * the App component.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages trigger
 * tool calls (file operations + run_task), which run the full BergAgents harness.
 */

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import type { UIMessage, TextUIPart } from 'ai';
import { useState } from 'react';
import type { SetStateAction } from 'react';
import { API_BASE } from '@/envConfig';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  parts?: Array<Record<string, unknown>>;
}

export interface UseAISDKChatReturn {
  messages: ChatMessage[];
  input: string;
  /** Direct state setter — compatible with InputBar's setInput prop. */
  setInput: (value: SetStateAction<string>) => void;
  /** Change handler — also compatible with InputBar. */
  handleInputChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  /** Send the current input message. */
  handleSend: () => void;
  isStreaming: boolean;
  error: string | null;
  isConnected: boolean;
  setMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
  stop: () => void;
  sendMessage: (content: string) => Promise<void>;
}

/**
 * Extract text content from a UIMessage's parts (v7 API).
 * In v7, UIMessage has `parts` instead of `content`.
 */
function messageText(msg: UIMessage): string {
  return msg.parts
    .filter((p): p is TextUIPart => p.type === 'text')
    .map((p) => p.text)
    .join('');
}

/**
 * Main chat hook — wraps AI SDK v7's useChat to talk to /api/chat/stream.
 *
 * Simple messages ("hello") get a direct LLM reply. Complex messages
 * trigger tool calls (file operations + run_task), which run the full
 * BergAgents harness. HITL approval requests surface as tool approval
 * parts in the AI SDK message stream.
 */
export function useAISDKChat(): UseAISDKChatReturn {
  // useChat v7 returns: messages, sendMessage, status, error, setMessages, stop
  // It does NOT return input/handleInputChange/handleSubmit — we manage input
  // state separately and call sendMessage directly.
  const [input, setInput] = useState('');

  const {
    messages: uiMessages,
    sendMessage: sdkSendMessage,
    status,
    error,
    setMessages: setUIMessages,
    stop,
  } = useChat({
    transport: new DefaultChatTransport({
      api: `${API_BASE}/api/chat/stream`,
    }),
  });

  const isStreaming = status === 'streaming' || status === 'submitted';

  // Convert AI SDK UIMessage[] to the simpler ChatMessage[] our UI expects.
  const messages: ChatMessage[] = uiMessages.map((msg) => ({
    id: msg.id,
    role: msg.role as 'user' | 'assistant' | 'system',
    content: messageText(msg),
    parts: [],
  }));

  const setMessages = (msgs: ChatMessage[]) => {
    setUIMessages(msgs as unknown as UIMessage[]);
  };

  const clearMessages = () => {
    setUIMessages([]);
  };

  // handleInputChange for a textarea/input — reads e.target.value.
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setInput(e.target.value);
  };

  // handleSend sends the current input via AI SDK's sendMessage.
  const handleSend = () => {
    if (!input.trim() || isStreaming) return;
    void sdkSendMessage({ text: input });
  };

  // Programmatic send (used by App's slash-command handler).
  const sendMessage = async (content: string) => {
    if (!content.trim()) return;
    await sdkSendMessage({ text: content });
  };

  return {
    messages,
    input,
    setInput,
    handleInputChange,
    handleSend,
    isStreaming,
    error: error ? String(error) : null,
    isConnected: true,
    setMessages,
    clearMessages,
    stop,
    sendMessage,
  };
}
