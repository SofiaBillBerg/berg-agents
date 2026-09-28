/*
 * Barrel export for the harness module.
 * Simplified — uses AI SDK v7's useChat directly, no custom harness classes.
 */

// Re-export types used by components.
export type {
  AgentInfo,
  HitlRequest,
  TaskResult,
  HarnessEvent,
  HitlDecisionInput,
} from './webhook';

// Main chat hook — wraps AI SDK v7's useChat.
export { useAISDKChat } from './useAISDKChat';
export type { ChatMessage, UseAISDKChatReturn } from './useAISDKChat';
