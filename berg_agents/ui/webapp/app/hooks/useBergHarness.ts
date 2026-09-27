/**
 * Typed Berg Harness hook.
 * Single source of truth for agent catalog, task execution, SSE streaming, HITL.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { z } from "zod";

import BuildAgentProxy, { apiFetch } from "@/envConfig";

const AGENT_URL = BuildAgentProxy;

// Resume-poll budget: ~90s after approval
const RESUME_POLL_INTERVAL_MS = 1500;
const RESUME_POLL_MAX_ATTEMPTS = 60;

// Zod schemas for UI-facing types (lightweight, no runtime parse gate yet)
export const ProviderInfoSchema = z.object({
  name: z.string(),
  model: z.string(),
  description: z.string().optional(),
  preferred_complexity: z.string().optional(),
  capabilities: z.array(z.string()).optional(),
});
export type ProviderInfo = z.infer<typeof ProviderInfoSchema>;

export const HarnessEventSchema = z.object({
  type: z.string(),
  data: z.unknown().optional(),
});
export type HarnessEvent = z.infer<typeof HarnessEventSchema>;

export type HitlDecisionInput =
  | string
  | { decision: string; edited_action?: unknown }
  | Array<{ decision: string; edited_action?: unknown }>;

function toInternalEvent(part: unknown): HarnessEvent {
  if (
    part &&
    typeof (part as Record<string, unknown>).type === "string" &&
    ((part as Record<string, unknown>).type as string).startsWith("data-") &&
    "data" in (part as Record<string, unknown>)
  ) {
    const p = part as { type: string; data: unknown };
    return { type: p.type.slice(5).replace(/-/g, "_"), data: p.data };
  }
  return part as HarnessEvent;
}

export function useBergHarness() {
  const [agents, setAgents] = useState<ProviderInfo[]>([]);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [subtasks, setSubtasks] = useState<unknown[]>([]);
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hitlRequest, setHitlRequest] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [learningStats, setLearningStats] = useState<unknown>(null);
  const [events, setEvents] = useState<HarnessEvent[]>([]);
  const threadRef = useRef<string | null>(null);
  const taskDescRef = useRef<string>("");
  const [isResuming, setIsResuming] = useState(false);
  const syncHitlRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const handleDataPart = useCallback((part: unknown) => {
    if (!part || typeof (part as { type?: unknown }).type !== "string") return;
    const p = part as { type: string; data?: unknown };
    if (p.type === "data-task-completed") {
      const data = (p.data ?? {}) as Record<string, unknown>;
      setResult(data);
      if (data.plan) setSubtasks(data.plan as unknown[]);
      setIsExecuting(false);
    } else if (p.type === "data-hitl-requested") {
      setHitlRequest({
        ...((p.data ?? {}) as Record<string, unknown>),
        description: taskDescRef.current,
      });
    }
    setEvents((prev) => [...prev, toInternalEvent(part)]);
  }, []);

  const handleChatError = useCallback((err: { message?: string }) => {
    setError(err?.message || "Task failed");
    setIsExecuting(false);
  }, []);

  const transport = useMemo(
    () => ({
      async sendMessages({ abortSignal }: { abortSignal?: AbortSignal }) {
        const threadId = threadRef.current;
        const resp = await fetch(
          `${AGENT_URL}/api/harness/${threadId}/events`,
          { signal: abortSignal },
        );
        if (!resp.ok || !resp.body)
          throw new Error(`Event stream failed: ${resp.statusText}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        return new ReadableStream({
          async pull(controller) {
            const { done, value } = await reader.read();
            if (done) {
              controller.close();
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith("data:")) continue;
              try {
                controller.enqueue(JSON.parse(trimmed.slice(5).trim()));
              } catch {
                /* partial */
              }
            }
          },
          cancel() {
            reader.cancel();
          },
        });
      },
      async reconnectToStream() {
        return null;
      },
    }),
    [],
  );

  const { stop } = useChat({
    transport,
    onData: handleDataPart,
    onError: handleChatError,
  });

  useEffect(() => {
    async function loadAgents() {
      try {
        const resp = await fetch(`${AGENT_URL}/api/agents`);
        if (resp.ok) setAgents(await resp.json());
      } catch (e) {
        console.warn("Failed to load agents:", e);
      }
    }
    loadAgents().catch((e) => console.error("Error loading agents:", e));
  }, []);

  const fetchLearningStats = useCallback(async () => {
    try {
      const resp = await fetch(`${AGENT_URL}/api/learning-stats`);
      if (resp.ok) setLearningStats(await resp.json());
    } catch (e) {
      console.warn("Failed to fetch learning stats:", e);
    }
  }, []);

  const executeTask = useCallback(
    async (
      description: string,
      taskType = "generic",
      metadata: Record<string, unknown> | null = null,
    ) => {
      setIsExecuting(true);
      setError(null);
      setResult(null);
      setSubtasks([]);
      setActiveAgent(null);
      setHitlRequest(null);
      syncHitlRef.current = null;
      taskDescRef.current = description ?? "";
      setEvents([
        { type: "task_started", data: { description, task_type: taskType } },
      ]);
      try {
        const resp = await fetch(`${AGENT_URL}/api/harness`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description, task_type: taskType, metadata }),
        });
        if (!resp.ok)
          throw new Error(`Task execution failed: ${resp.statusText}`);
        const data = (await resp.json()) as Record<string, unknown>;
        if (data.status === "needs_human_review") {
          setHitlRequest({ ...data, description });
          syncHitlRef.current = (data.task_id as string) ?? null;
          setEvents((prev) => [...prev, { type: "hitl_requested", data }]);
        } else {
          setResult(data);
          if (data.plan) setSubtasks(data.plan as unknown[]);
          syncHitlRef.current = null;
          setEvents((prev) => [...prev, { type: "task_completed", data }]);
        }
        return data;
      } catch (e: unknown) {
        const msg = (e as Error).message ?? String(e);
        setError(msg);
        setEvents((prev) => [
          ...prev,
          { type: "task_failed", data: { error: msg } },
        ]);
        throw e;
      } finally {
        setIsExecuting(false);
      }
    },
    [],
  );

  const pollSyncResume = useCallback(
    async (threadId: string): Promise<Record<string, unknown> | null> => {
      setIsResuming(true);
      setError(null);
      try {
        for (
          let attempt = 0;
          attempt < RESUME_POLL_MAX_ATTEMPTS;
          attempt += 1
        ) {
          if (!mountedRef.current) return null;
          try {
            const resp = await apiFetch(`/api/threads/${threadId}`);
            if (resp.ok) {
              const data = (await resp.json()) as {
                result?: Record<string, unknown>;
                events?: HarnessEvent[];
              };
              const resultData = data.result;
              const eventsData = data.events || [];
              const terminal = eventsData.find(
                (e) => e.type === "task_completed" || e.type === "task_failed",
              );
              if (terminal) {
                if (terminal.type === "task_failed") {
                  const payload = terminal.data as Record<string, unknown>;
                  const message = (payload?.error as string)
                    ? String(payload.error)
                    : "Task failed after approval";
                  setError(message);
                  syncHitlRef.current = null;
                  setEvents((prev) => [
                    ...prev,
                    { type: "task_failed", data: payload },
                  ]);
                  return null;
                }
                if (resultData) {
                  setResult(resultData);
                  if (resultData.plan)
                    setSubtasks(resultData.plan as unknown[]);
                  syncHitlRef.current = null;
                  setEvents((prev) => [
                    ...prev,
                    { type: "task_completed", data: resultData },
                  ]);
                  return resultData;
                }
              }
              if (resultData && resultData.status === "completed") {
                setResult(resultData);
                if (resultData.plan) setSubtasks(resultData.plan as unknown[]);
                syncHitlRef.current = null;
                setEvents((prev) => [
                  ...prev,
                  { type: "task_completed", data: resultData },
                ]);
                return resultData;
              }
              if (resultData && resultData.status === "failed") {
                setError(String((resultData.error as string) || "Task failed"));
                syncHitlRef.current = null;
                setEvents((prev) => [
                  ...prev,
                  { type: "task_failed", data: resultData },
                ]);
                return null;
              }
            }
          } catch {
            /* transient */
          }
          await new Promise((resolve) =>
            setTimeout(resolve, RESUME_POLL_INTERVAL_MS),
          );
        }
        setError(
          "Approval recorded, but the resumed task did not finish in time — check the thread export and retry.",
        );
        return null;
      } finally {
        if (mountedRef.current) setIsResuming(false);
      }
    },
    [],
  );

  const respondToHitl = useCallback(
    async (threadId: string, decision: HitlDecisionInput) => {
      let finalResult: Record<string, unknown> | null = null;
      try {
        let payload: Record<string, unknown> = { decision: "approve" };
        if (decision && typeof decision === "object") {
          if (Array.isArray(decision)) {
            const first = decision[0] as {
              decision: string;
              edited_action?: unknown;
            };
            payload = {
              decision: first?.decision || "approve",
              edited_action: first?.edited_action || null,
            };
          } else {
            const d = decision as {
              decision: string;
              edited_action?: unknown;
            };
            payload = {
              decision: d.decision || "approve",
              edited_action: d.edited_action || null,
            };
          }
        } else if (typeof decision === "string") payload = { decision };
        const resp = await fetch(
          `${AGENT_URL}/api/harness/${threadId}/respond`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
        );
        if (!resp.ok)
          throw new Error(`HITL response failed: ${resp.statusText}`);
        setHitlRequest(null);
        if (
          syncHitlRef.current &&
          threadId &&
          syncHitlRef.current === threadId
        ) {
          // Poll until the approved task completes so we can show its answer
          finalResult = await pollSyncResume(threadId);
          if (!finalResult) return null;
        }
        return finalResult;
      } catch (e: unknown) {
        console.error("Failed to respond to HITL:", e);
        setError((e as Error).message);
        return null;
      }
    },
    [pollSyncResume],
  );

  const createThread = useCallback(async () => {
    try {
      const resp = await fetch(`${AGENT_URL}/api/threads`, { method: "POST" });
      if (resp.ok) return (await resp.json()).thread_id as string;
    } catch (e) {
      console.warn("Failed to create thread:", e);
    }
    return null;
  }, []);

  const cancelTask = useCallback(
    async (threadId: string) => {
      try {
        await stop();
        await fetch(`${AGENT_URL}/api/threads/${threadId}/cancel`, {
          method: "POST",
        });
        setIsExecuting(false);
      } catch (e) {
        console.warn("Failed to cancel task:", e);
      }
    },
    [stop],
  );

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      stop().catch((e) => console.error("Error stopping chat on unmount:", e));
    };
  }, [stop]);

  return {
    agents,
    activeAgent,
    subtasks,
    isExecuting,
    isResuming,
    result,
    error,
    hitlRequest,
    learningStats,
    events,
    executeTask,
    respondToHitl,
    createThread,
    cancelTask,
    fetchLearningStats,
  };
}

// Keep old name as alias for incremental migration
export const useHarness = useBergHarness;
