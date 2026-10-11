/*
 * <one line to give the program's name and a brief idea of what it does.>
 *
 * Copyright (c) 2026.
 *         Copyright (C) <year>  <name of author>
 *
 *         This program is free software: you can redistribute it and/or modify
 *         it under the terms of the GNU Affero General Public License as
 *         published by the Free Software Foundation, either version 3 of the
 *         License, or (at your option) any later version.
 *
 *         This program is distributed in the hope that it will be useful,
 *         but WITHOUT ANY WARRANTY; without even the implied warranty of
 *         MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *         GNU Affero General Public License for more details.
 *
 *         You should have received a copy of the GNU Affero General Public License
 *         along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 */

/*
 * Type definitions for the harness backend API contract.
 *
 * This file provides TypeScript types that mirror the Python backend's
 * response schemas (see berg_agents/ui/schemas.py). It replaces the old
 * complex IHarness interface - the frontend now uses AI SDK v6's useChat
 * hook directly against /api/chat/stream.
 */

/** Agent info returned by /api/agents */
export interface AgentInfo {
  name: string;
  model: string;
  description?: string;
  preferred_complexity?: string;
  capabilities?: string[];
}

/** HITL request details from the backend */
export interface HitlRequest {
  task_id: string;
  description: string;
  review_reasons: string[];
  risk_level: "low" | "medium" | "high";
  complexity: {
    value: "simple" | "standard" | "complex";
    description: string;
  };
}

/** Task result from the backend */
export interface TaskResult {
  status: "completed" | "failed" | "needs_human_review";
  task_id: string;
  complexity: {
    value: "simple" | "standard" | "complex";
    description: string;
  };
  implementation: {
    answer: string;
    model_run?: {
      files_changed?: Array<Record<string, unknown>>;
    };
  };
  plan?: unknown[];
  curation?: { status: string };
  subagents?: string[];
  background_tasks?: string[];
}

/** Simple harness event (backward compat for event logging) */
export interface HarnessEvent {
  type: string;
  data?: unknown;
}

/** HITL decision input */
export type HitlDecisionInput =
  | string
  | { decision: "approve" | "reject" | "edit"; edited_action?: unknown }
  | Array<{ decision: "approve" | "reject" | "edit"; edited_action?: unknown }>;
