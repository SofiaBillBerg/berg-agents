import { useCallback, useEffect, useRef, useState } from "react";

import BuildAgentProxy from "@/envConfig.ts";

("../envConfig.ts");
const AGENT_URL = BuildAgentProxy;
/**
 * React hook for interacting with the orchestrator-based multi-agent system.
 * Provides agent discovery, task execution, SSE streaming, and HITL support.
 */
export function useOrchestrator() {
  const [agents, setAgents] = useState([]);
  const [activeAgent, setActiveAgent] = useState(null);
  const [subtasks, setSubtasks] = useState([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [hitlRequest, setHitlRequest] = useState(null);
  const [learningStats, setLearningStats] = useState(null);
  const [events, setEvents] = useState([]);
  const eventSourceRef = useRef(null);

  // Fetch available agents on mount
  useEffect(() => {
    async function loadAgents() {
      try {
        const resp = await fetch(`${AGENT_URL}/api/agents`);
        if (resp.ok) {
          const data = await resp.json();
          setAgents(data);
        }
      } catch (e) {
        console.warn("Failed to load agents:", e);
      }
    }
    loadAgents();
  }, []);

  // Fetch learning stats
  const fetchLearningStats = useCallback(async () => {
    try {
      const resp = await fetch(`${AGENT_URL}/api/learning-stats`);
      if (resp.ok) {
        const data = await resp.json();
        setLearningStats(data);
      }
    } catch (e) {
      console.warn("Failed to fetch learning stats:", e);
    }
  }, []);

  // Execute a task synchronously
  const executeTask = useCallback(
    async (description, taskType = "generic", metadata = null) => {
      setIsExecuting(true);
      setError(null);
      setResult(null);
      setSubtasks([]);
      setActiveAgent(null);

      try {
        const resp = await fetch(`${AGENT_URL}/api/orchestrate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description, task_type: taskType, metadata }),
        });

        if (!resp.ok) {
          throw new Error(`Task execution failed: ${resp.statusText}`);
        }

        const data = await resp.json();

        if (data.status === "needs_human_review") {
          setHitlRequest(data);
        } else {
          setResult(data);
          if (data.plan) {
            setSubtasks(data.plan);
          }
        }

        return data;
      } catch (e) {
        setError(e.message);
        throw e;
      } finally {
        setIsExecuting(false);
      }
    },
    [],
  );

  // Submit a task for streaming execution
  const submitTaskStream = useCallback(
    async (threadId, description, taskType = "generic") => {
      setIsExecuting(true);
      setError(null);
      setEvents([]);

      try {
        // Start the task
        await fetch(`${AGENT_URL}/api/orchestrate/${threadId}/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description, task_type: taskType }),
        });

        // Connect to SSE stream
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
        }

        const es = new EventSource(
          `${AGENT_URL}/api/orchestrate/${threadId}/events`,
        );
        eventSourceRef.current = es;

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            setEvents((prev) => [...prev, data]);

            if (data.type === "task_completed") {
              setResult(data.data);
              if (data.data?.plan) {
                setSubtasks(data.data.plan);
              }
              setIsExecuting(false);
              es.close();
            } else if (data.type === "hitl_requested") {
              setHitlRequest(data.data);
            } else if (data.type === "task_failed") {
              setError(data.data?.error || "Task failed");
              setIsExecuting(false);
              es.close();
            }
          } catch (e) {
            console.warn("Failed to parse SSE event:", e);
          }
        };

        es.onerror = () => {
          setIsExecuting(false);
          es.close();
        };
      } catch (e) {
        setError(e.message);
        setIsExecuting(false);
      }
    },
    [],
  );

  // Respond to HITL interrupt
  const respondToHitl = useCallback(async (threadId, decision) => {
    try {
      await fetch(`${AGENT_URL}/api/orchestrate/${threadId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      setHitlRequest(null);
    } catch (e) {
      console.error("Failed to respond to HITL:", e);
    }
  }, []);

  // Create a new thread
  const createThread = useCallback(async () => {
    try {
      const resp = await fetch(`${AGENT_URL}/api/threads`, { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        return data.thread_id;
      }
    } catch (e) {
      console.warn("Failed to create thread:", e);
    }
    return null;
  }, []);

  // Cancel a running task
  const cancelTask = useCallback(async (threadId) => {
    try {
      await fetch(`${AGENT_URL}/api/threads/${threadId}/cancel`, {
        method: "POST",
      });
      setIsExecuting(false);
    } catch (e) {
      console.warn("Failed to cancel task:", e);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  return {
    agents,
    activeAgent,
    subtasks,
    isExecuting,
    result,
    error,
    hitlRequest,
    learningStats,
    events,
    executeTask,
    submitTaskStream,
    respondToHitl,
    createThread,
    cancelTask,
    fetchLearningStats,
  };
}
