/*
 * Harness interface - defines the contract between Python backend and React frontend.
 * This abstraction allows for easy testing and clean separation of concerns.
 */

import { z } from "zod";

// Task complexity type definitions
export const TaskComplexitySchema = z.enum(["simple", "standard", "complex"]);

export interface TaskComplexity {
  value: "simple" | "standard" | "complex";
  description: string;
}

// Agent type definitions
export const AgentInfoSchema = z.object({
  name: z.string(),
  model: z.string(),
  description: z.string().optional(),
  preferred_complexity: z.string().optional(),
  capabilities: z.array(z.string()).optional(),
});

export type AgentInfo = z.infer<typeof AgentInfoSchema>;

// Task complexity interface for TaskResult
export interface TaskResultComplexity {
  value: "simple" | "standard" | "complex";
  description: string;
}

// Implementation result interface
export interface ImplementationResult {
  answer: string;
  model_run?: {
    files_changed?: Record<string, unknown>[];
  };
}

// Curation status interface
export interface CurationStatus {
  status: string;
}

// Task result type definitions
export const TaskResultSchema = z.object({
  status: z.enum(["completed", "failed", "needs_human_review"]),
  task_id: z.string(),
  complexity: z.object({ value: TaskComplexitySchema }),
  implementation: z.object({
    answer: z.string(),
    model_run: z.object({
      files_changed: z.array(z.record(z.string(), z.any())),
    }).optional(),
  }),
  plan: z.array(z.any()).optional(),
  curation: z.object({
    status: z.string(),
  }).optional(),
  subagents: z.array(z.string()).optional(),
  background_tasks: z.array(z.string()).optional(),
});

export type TaskResult = z.infer<typeof TaskResultSchema>;

// Harness event type definitions
export const HarnessEventSchema = z.object({
  type: z.string(),
  data: z.unknown().optional(),
});

export type HarnessEvent = z.infer<typeof HarnessEventSchema>;

// HITL request type definitions
export interface HitlRequest {
  task_id: string;
  description: string;
  review_reasons: string[];
  risk_level: "low" | "medium" | "high";
  complexity: TaskComplexity;
}

// HITL decision input types
export type HitlDecisionInput = 
  | string 
  | { decision: "approve" | "reject" | "edit"; edited_action?: unknown }
  | Array<{ decision: "approve" | "reject" | "edit"; edited_action?: unknown }>
;

// Helper functions for type validation
export function isTaskResult(value: unknown): value is TaskResult {
  return TaskResultSchema.safeParse(value).success;
}

export function isAgentInfo(value: unknown): value is AgentInfo {
  return AgentInfoSchema.safeParse(value).success;
}

export function isHarnessEvent(value: unknown): value is HarnessEvent {
  return HarnessEventSchema.safeParse(value).success;
}

// The main harness interface - clean contract without implementation details
export interface IHarness {
  // Core operations
  executeTask(description: string, taskType?: string): Promise<TaskResult>;
  getAgents(): Promise<AgentInfo[]>;
  fetchLearningStats(): Promise<unknown>;
  
  // HITL operations
  respondToHitl(threadId: string, decision: HitlDecisionInput): Promise<TaskResult | null>;
  
  // State management
  subscribeToEvents(callback: (event: HarnessEvent) => void): () => void;
  getCurrentEvents(): HarnessEvent[];
  getCurrentResult(): TaskResult | null;
  getHitlRequest(): HitlRequest | null;
  
  // Connection
  isConnected(): boolean;
  reconnect(): void;
}

// Default task complexity descriptions
export const TASK_COMPLEXITY_DESCRIPTIONS: Record<TaskComplexity["value"], string> = {
  simple: "Simple, straightforward tasks that require minimal context",
  standard: "Standard tasks that require moderate analysis and planning",
  complex: "Complex tasks that require significant planning, analysis, and oversight",
};

// Default agent configurations for fallback
export const DEFAULT_AGENTS: AgentInfo[] = [
  {
    name: "researcher",
    model: "gpt-4",
    description: "Research and analysis agent",
    preferred_complexity: "standard",
    capabilities: ["web_search", "document_analysis", "data_extraction"],
  },
  {
    name: "coder",
    model: "claude-3", 
    description: "Code generation and debugging agent",
    preferred_complexity: "complex",
    capabilities: ["code_generation", "debugging", "testing"],
  },
  {
    name: "designer",
    model: "gpt-4-vision",
    description: "UI/UX and creative design agent", 
    preferred_complexity: "standard",
    capabilities: ["ui_design", "visual_design", "prototyping"],
  },
];

export const DEFAULT_HITL_REQUEST: HitlRequest = {
  task_id: "",
  description: "Task requires human review",
  review_reasons: [
    "Potential security implications",
    "Privacy-sensitive data handling", 
    "Compliance verification required"
  ],
  risk_level: "high",
  complexity: { value: "complex", description: "Complex tasks requiring oversight" },
};