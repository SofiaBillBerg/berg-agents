/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of the
 * License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * The specialists, as seen from TypeScript.
 *
 * A specialist is a **run of its own** in berg's Python backend: it has a run
 * id, a durable record, its gates, and its own stream. This module is the only
 * place the orchestrator talks to one, so the seam between the two languages is
 * a handful of HTTP calls rather than a protocol each side re-implements.
 *
 * Why the orchestrator is TypeScript at all: a `WorkflowAgent` SUSPENDS inside
 * its run on a pause, where berg's Python host ENDS the pass and resumes as a
 * new run. Suspension is what lets the user keep talking to the orchestrator
 * while it waits — and planning *with* the user mid-flight is the orchestrator's
 * whole job (decisions-log, 2026-11-12).
 *
 * Never npm here: `berg_agents/ui/webapp` is a bun project.
 */

import {API_BASE} from "@/envConfig";
import {fetch as workflowFetch} from "workflow";

/** One specialist run, as the backend reports it. */
export interface SpecialistRun {
    /** The run id — the only handle the orchestrator needs. */
    runId: string;
    /** Which specialist is running it. */
    agentName: string;
    /** The turn token, which is what a steer and a gate answer are keyed on. */
    token: string;
}

/** What a specialist is doing, in the terms a caller acts on. */
export type SpecialistState = "pending" | "working" | "waiting" | "done";

/** A report of finished work, in the terms a user reads. */
export interface SpecialistReport {
    runId: string;
    state: SpecialistState;
    status: string;
    /** What the specialist said, in its own words. */
    said: string;
    /** What it did: one entry per tool call, with the result. */
    did: Array<{ tool: string; args: unknown; result: string }>;
    /** How many frames its transcript holds. */
    frames: number;
    /** The calls a `waiting` specialist needs answered. */
    pending: Array<{ tool_call_id: string; tool_name: string; args: unknown }>;
}

/**
 * The absolute origin to reach berg's API from *inside a workflow step*.
 *
 * `API_BASE` is empty in production on purpose — the browser and the server are
 * same-origin, so a relative `/api/...` is correct there. But `workflow`'s
 * `fetch` runs inside a step and requires an absolute URL; handed a relative
 * path it fails with `Failed to parse URL from /api/agents` (found
 * 2026-11-12, after the step-fetch change: this broke every specialist tool
 * while the page still looked healthy).
 *
 * So: use `API_BASE` when set, otherwise name this server explicitly. The
 * rewrite in `next.config.mjs` sends `/api/*` to Python, so pointing at our own
 * origin goes through that same path and keeps one routing rule.
 *
 * @returns An origin with no trailing slash.
 */
function backendOrigin(): string {
    if (API_BASE) return API_BASE;
    const host = process.env.HOSTNAME || "127.0.0.1";
    const port = process.env.PORT || "3100";
    return `http://${host}:${port}`;
}

/**
 * One HTTP call to berg's backend, with a useful error when it fails.
 *
 * Two deliberate choices here:
 *
 * - **`workflow`'s `fetch`, not the global one.** These calls are made from
 *   inside a workflow function (`WorkflowAgent` tool execution), where the
 *   runtime forbids global `fetch` — it fails with *"Global fetch is
 *   unavailable in workflow functions"*. `workflow`'s own `fetch` is hoisted
 *   into a step, so the call is durable and retried like the rest of the turn.
 * - **`API_BASE` rather than a second base-URL rule.** `envConfig` already
 *   resolves where the Python backend lives (same-origin in production,
 *   `NEXT_PUBLIC_API_BASE_URL` under `next dev`); only the fetch differs.
 */
async function call(
    path: string,
    init?: RequestInit,
): Promise<Record<string, unknown>> {
    const response = await workflowFetch(`${backendOrigin()}${path}`, {
        ...init,
        headers: {"Content-Type": "application/json", ...(init?.headers ?? {})},
        cache: "no-store"});
    const text = await response.text();
    if (!response.ok) {
        // The detail matters: these routes answer 404 for an unknown agent and
        // 409 for a spent decision, and both are actionable rather than fatal.
        throw new Error(
            `${path} -> ${response.status} ${text.slice(0, 200)}`,
        );
    }
    return text.trim() ? (JSON.parse(text) as Record<string, unknown>) : {};
}

/** The specialists berg registers, so the orchestrator offers real names. */
export async function listSpecialists(): Promise<string[]> {
    const agents = (await call("/api/agents")) as unknown;
    if (!Array.isArray(agents)) return [];
    return agents
        .map((entry) => String((entry as { name?: unknown })?.name ?? ""))
        .filter(Boolean);
}

/** Start a specialist's turn as a run of its own. */
export async function startSpecialist(
    agentName: string,
    task: string,
    rootDir = ".",
): Promise<SpecialistRun> {
    const started = await call("/api/workflow/chat", {
        method: "POST",
        body: JSON.stringify({
            prompt: task,
            agent: agentName,
            root_dir: rootDir})});
    return {
        runId: String(started.run_id ?? ""),
        token: String(started.token ?? ""),
        agentName};
}

/** Read what a specialist is doing right now. */
export async function specialistState(
    runId: string,
): Promise<{ state: SpecialistState; status: string; pending: SpecialistReport["pending"] }> {
    const state = await call(`/api/workflow/chat/${runId}/state`);
    return {
        state: String(state.state ?? "pending") as SpecialistState,
        status: String(state.status ?? "unknown"),
        pending: (state.pending as SpecialistReport["pending"]) ?? []};
}

/** Read what a specialist said and did, from its durable record. */
export async function specialistReport(
    runId: string,
): Promise<SpecialistReport> {
    const report = await call(`/api/workflow/chat/${runId}/report`);
    return {
        runId: String(report.run_id ?? runId),
        state: String(report.state ?? "pending") as SpecialistState,
        status: String(report.status ?? "unknown"),
        said: String(report.said ?? ""),
        did: (report.did as SpecialistReport["did"]) ?? [],
        frames: Number(report.frames ?? 0),
        pending: (report.pending as SpecialistReport["pending"]) ?? []};
}

/**
 * Answer a specialist's gate.
 *
 * A `steer` travels with the decision and becomes the denial's message, which
 * makes the specialist re-plan instead of executing arguments it had already
 * committed — proven against the Python host.
 */
export async function answerSpecialist(
    runId: string,
    options: { approved: boolean; reason?: string; steer?: string },
): Promise<SpecialistRun> {
    const answered = await call(`/api/workflow/chat/${runId}/approval`, {
        method: "POST",
        body: JSON.stringify({
            decision: options.approved ? "approved" : "rejected",
            reason: options.reason,
            steer: options.steer})});
    return {
        runId: String(answered.run_id ?? ""),
        token: String(answered.token ?? ""),
        agentName: String(answered.agent_name ?? "")};
}

/** Send the user's instruction to a specialist's turn. */
export async function steerSpecialist(
    runId: string,
    text: string,
): Promise<{ runId: string; delivered: boolean }> {
    const steered = await call(`/api/workflow/chat/${runId}/steer`, {
        method: "POST",
        body: JSON.stringify({ text })});
    return {
        runId: String(steered.run_id ?? runId),
        delivered: Boolean(steered.delivered)};
}

/**
 * Stop a specialist.
 *
 * The backend picks the mechanism from the specialist's state — a `waiting` run
 * is withdrawn by denying its gate, a `working` one is terminated — because those
 * are two different operations on two different states.
 */
export async function stopSpecialist(
    runId: string,
    reason = "stopped by the user",
): Promise<{ stopped: boolean; how: string }> {
    const stopped = await call(`/api/workflow/chat/${runId}/stop`, {
        method: "POST",
        body: JSON.stringify({ reason })});
    return {
        stopped: Boolean(stopped.stopped),
        how: String(stopped.how ?? "unknown")};
}
