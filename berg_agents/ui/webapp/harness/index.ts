/*
 * Barrel export for the harness module.
 * Centralizes all exports for clean imports throughout the app.
 */

export type {
  AgentInfo,
  HarnessEvent,
  HitlRequest,
  IHarness,
  TaskComplexity,
  TaskResult,
  HitlDecisionInput,
} from './webhook';

export {
  AgentInfoSchema,
  HarnessEventSchema,
  TaskResultSchema,
  isAgentInfo,
  isHarnessEvent,
  isTaskResult,
} from './webhook';

export { HarnessProvider, useHarness } from './harness-provider';

export {
  useAgents,
  useHarnessEvents,
  useHarnessState,
  useHitl,
  useLearningStats,
  useTaskExecution,
} from './hooks';

export { MockHarness } from './mock-harness';
export { RealHarness } from './real-harness';

export { useAISDKChat, type ChatMessage } from './useAISDKChat';
export {
  eventToAISDKPart,
  eventsToMessages,
  createHarnessEncoder,
} from './ai-sdk-streaming';