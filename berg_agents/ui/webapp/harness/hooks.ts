/*
 * Simple hooks for harness operations.
 * These replace the complex useBergHarness hook with focused, testable hooks.
 */

import { useState, useEffect, useCallback } from 'react';

import type { IHarness, HarnessEvent, TaskResult, HitlRequest, AgentInfo } from './webhook';
import { useHarness } from './harness-provider';

// Hook for task execution
export function useTaskExecution() {
  const { harness } = useHarness();
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const executeTask = useCallback(async (description: string, taskType: string = "generic") => {
    if (!harness) {
      throw new Error('Harness not connected');
    }

    setIsExecuting(true);
    setError(null);
    setResult(null);

    try {
      const taskResult = await harness.executeTask(description, taskType);
      setResult(taskResult);
      return taskResult;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Task execution failed';
      setError(errorMessage);
      throw err;
    } finally {
      setIsExecuting(false);
    }
  }, [harness]);

  return {
    executeTask,
    isExecuting,
    result,
    error,
    clearResult: () => setResult(null),
    clearError: () => setError(null),
  };
}

// Hook for agents management
export function useAgents() {
  const { harness } = useHarness();
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    if (!harness) {
      return { agents: [], error: 'Harness not connected' };
    }

    setIsLoading(true);
    setError(null);

    try {
      const agentsList = await harness.getAgents();
      setAgents(agentsList);
      return { agents: agentsList, error: null };
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load agents';
      setError(errorMessage);
      return { agents: [], error: errorMessage };
    } finally {
      setIsLoading(false);
    }
  }, [harness]);

  useEffect(() => {
    loadAgents().catch(() => {
      // Error is already handled in state
    });
  }, [loadAgents]);

  return {
    agents,
    isLoading,
    error,
    loadAgents,
    refreshAgents: loadAgents, // Alias for backward compatibility
  };
}

// Hook for learning stats
export function useLearningStats() {
  const { harness } = useHarness();
  const [stats, setStats] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    if (!harness) {
      return { stats: null, error: 'Harness not connected' };
    }

    setIsLoading(true);
    setError(null);

    try {
      const learningStats = await harness.fetchLearningStats();
      setStats(learningStats);
      return { stats: learningStats, error: null };
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch learning stats';
      setError(errorMessage);
      return { stats: null, error: errorMessage };
    } finally {
      setIsLoading(false);
    }
  }, [harness]);

  useEffect(() => {
    fetchStats().catch(() => {
      // Error is already handled in state
    });
  }, [fetchStats]);

  return {
    stats,
    isLoading,
    error,
    fetchStats,
  };
}

// Hook for event monitoring
export function useHarnessEvents() {
  const { harness } = useHarness();
  const [events, setEvents] = useState<HarnessEvent[]>([]);

  useEffect(() => {
    if (!harness) return;

    const handleEvent = (event: HarnessEvent) => {
      setEvents(prev => [...prev, event]);
    };

    // Subscribe to events
    const unsubscribe = harness.subscribeToEvents(handleEvent);

    // Get current events from harness
    setEvents(harness.getCurrentEvents());

    return () => {
      unsubscribe();
    };
  }, [harness]);

  return { events };
}

// Hook for HITL management
export function useHitl() {
  const { harness } = useHarness();
  const [hitlRequest, setHitlRequest] = useState<HitlRequest | null>(null);

  useEffect(() => {
    if (!harness) return;

    const updateHitl = () => {
      const currentHitl = harness.getHitlRequest();
      setHitlRequest(currentHitl);
    };

    updateHitl();

    // Listen for HITL changes through events
    const handleEvent = (event: HarnessEvent) => {
      if (event.type.includes('hitl')) {
        updateHitl();
      }
    };

    harness.subscribeToEvents(handleEvent);

    return () => {
      harness.subscribeToEvents(() => {});
    };
  }, [harness]);

  const respondToHitl = useCallback(async (threadId: string, decision: Record<string, unknown> | string | Array<Record<string, unknown>>) => {
    if (!harness) {
      throw new Error('Harness not connected');
    }

    return await harness.respondToHitl(threadId, decision as never);
  }, [harness]);

  return {
    hitlRequest,
    respondToHitl,
    clearHitl: () => setHitlRequest(null),
  };
}

// Combined hook for common use cases - returns structured state
interface HarnessState {
  connection: {
    isConnected: boolean;
    isLoading: boolean;
    error: string | null;
  };
  agents: {
    data: AgentInfo[];
    isLoading: boolean;
    error: string | null;
    refreshAgents: () => Promise<{ agents: AgentInfo[]; error: string | null }>;
  };
  learning: {
    stats: unknown;
    isLoading: boolean;
    error: string | null;
    fetchStats: () => Promise<{ stats: unknown; error: string | null }>;
  };
  task: {
    result: TaskResult | null;
    isExecuting: boolean;
    error: string | null;
    executeTask: (description: string, taskType?: string) => Promise<TaskResult>;
    clearResult: () => void;
    clearError: () => void;
  };
  events: HarnessEvent[];
  hitl: HitlRequest | null;
  respondToHitl: (threadId: string, decision: Record<string, unknown> | string | Array<Record<string, unknown>>) => Promise<TaskResult | null>;
}

export function useHarnessState(): HarnessState {
  const harnessContext = useHarness();
  const { harness, isConnected, isLoading: contextLoading, error: contextError } = harnessContext;
  const taskExecution = useTaskExecution();
  const agentsState = useAgents();
  const learningState = useLearningStats();
  const eventsState = useHarnessEvents();
  const hitlState = useHitl();

  return {
    connection: {
      isConnected,
      isLoading: contextLoading,
      error: contextError,
    },
    agents: {
      data: agentsState.agents,
      isLoading: agentsState.isLoading,
      error: agentsState.error,
      refreshAgents: agentsState.refreshAgents,
    },
    learning: {
      stats: learningState.stats,
      isLoading: learningState.isLoading,
      error: learningState.error,
      fetchStats: learningState.fetchStats,
    },
    task: {
      result: taskExecution.result,
      isExecuting: taskExecution.isExecuting,
      error: taskExecution.error,
      executeTask: taskExecution.executeTask,
      clearResult: taskExecution.clearResult,
      clearError: taskExecution.clearError,
    },
    events: eventsState.events,
    hitl: hitlState.hitlRequest,
    respondToHitl: hitlState.respondToHitl,
  };
}

// Legacy aliases for backward compatibility
export const useHarnessAgents = useAgents;
export const useHarnessLearning = useLearningStats;
export const useHarnessEventsLegacy = useHarnessEvents;