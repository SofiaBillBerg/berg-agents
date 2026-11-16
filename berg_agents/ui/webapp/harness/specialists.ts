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
 * whole job.
 *
 * Never npm here: `berg_agents/ui/webapp` is a bun project.
 */

import {fetch as workflowFetch} from "workflow";

import {API_BASE} from "@/envConfig";

/** One specialist run, as the backend reports it. */
export interface SpecialistRun {
    /** The run id — the only handle the orchestrator needs. */
    runId: string;
    /** Which specialist is running it. */
    agentName: string;
    /** The turn token, which is what a steer and a gate answer are keyed on. */
    token: string;
    /** Which model the route resolved for this run; empty when unknown. */
    model: string;
    /** Why the call did not happen, when it did not. */
    error?: string;
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
 * The absolute origin to reach berg's PYTHON backend, from inside a workflow
 * step.
 *
 * `API_BASE` is empty in production on purpose: the browser and this server are
 * same-origin, so a relative `/api/...` resolves for the client. `workflow`'s
 * `fetch` runs inside a step and requires an absolute URL, so the origin has to
 * be named here instead.
 */
function backendOrigin(): string {
    if (API_BASE) return API_BASE;
    const host = process.env.BERG_BACKEND_HOST || "127.0.0.1";
    const port = process.env.BERG_BACKEND_PORT || "8001";
    return `http://${host}:${port}`;
}

/**
 * One HTTP call to berg's backend, with a useful error when it fails.
 *
 * Two deliberate choices here:
 *
 * - **`workflow`'s `fetch`, not the global one.** These calls run inside
 *   workflow functions (WorkflowAgent tool execution), where the runtime
 *   forbids global `fetch`. `workflow`'s own `fetch` is hoisted into a step, so
 *   the call is durable and retried like the rest of the turn.
 * - **`API_BASE` rather than a second base-URL rule.** `envConfig` already
 *   resolves where the Python backend lives; only the fetch differs.
 */
/**
 * One HTTP call to berg's Python backend, with a useful error when it fails.
 *
 * Exported because it is THE seam: the orchestrator's own tools (workspace
 * reads, and the MCP and context surfaces) reach berg through here too, rather
 * than each module growing its own copy of the origin and the fetch rules.
 *
 * Two deliberate choices here:
 *
 * - **`workflow`'s `fetch`, not the global one.** These calls run inside
 *   workflow functions (WorkflowAgent tool execution), where the runtime
 *   forbids global `fetch`. `workflow`'s own `fetch` is hoisted into a step, so
 *   the call is durable and retried like the rest of the turn.
 * - **`API_BASE` rather than a second base-URL rule.** `envConfig` already
 *   resolves where the Python backend lives; only the fetch differs.
 *
 * @param path - The path, relative to the backend's origin.
 * @param init - The request init, when the call carries a body.
 * @returns The parsed JSON body, or an empty object for an empty one.
 */
export async function callBackend(
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
    // A step even though it only reads: the docs' point is that a tool without
    // it re-executes on replay, so a replayed turn could report a specialist
    // list that has since changed. Recorded, the turn is consistent with itself.
    "use step";
    const agents = (await callBackend("/api/agents")) as unknown;
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
    // A step, not an inline call. Starting a specialist begins a real run in
    // the Python backend, and a tool that is not a step re-executes on replay —
    // which would start a SECOND specialist for one instruction after a crash or
    // a retry. As a step its result is recorded, so a replay reads back the run
    // id that was already reported instead of starting another one.
    "use step";
    const started = await callBackend("/api/workflow/chat", {
        method: "POST",
        body: JSON.stringify({
            prompt: task,
            agent: agentName,
            root_dir: rootDir})});
    return {
        runId: String(started.run_id ?? ""),
        token: String(started.token ?? ""),
        agentName,
        // The model the route resolved for this run, so the specialist that just
        // started can be announced with its brain instead of being a black box.
        model: String(started.model ?? "")};
}

/** Read what a specialist is doing right now. */
export async function specialistState(
    runId: string,
): Promise<{ state: SpecialistState; status: string; pending: SpecialistReport["pending"] }> {
    // A step for the same reason as the list read: a replay then reports the state
    // the turn actually acted on rather than a fresh one.
    "use step";
    const state = await callBackend(`/api/workflow/chat/${runId}/state`);
    return {
        state: String(state.state ?? "pending") as SpecialistState,
        status: String(state.status ?? "unknown"),
        pending: (state.pending as SpecialistReport["pending"]) ?? []};
}

/** Read what a specialist said and did, from its durable record. */
export async function specialistReport(
    runId: string,
): Promise<SpecialistReport> {
    // A step for the same reason as the state read: the report a turn cites is the
    // one it actually read.
    "use step";
    const report = await callBackend(`/api/workflow/chat/${runId}/report`);
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
/**
 * A run id this session can act on, or an explanation when there isn't one.
 *
 * A tool that builds a URL from whatever it was given will happily ask berg for
 * `/api/workflow/chat//approval` — an empty id, a 404, and a failed step after
 * three retries, all because the model did not have a run id in hand. Refusing
 * here names what is missing instead: the run id `start_specialist` returned.
 *
 * @param runId - The id the model supplied.
 * @returns The id to use, or null when there is none.
 */
//: What the model is told when it acts on a specialist it never started.
const requireRunIdMessage =
    "No run id. Use the one start_specialist returned for that specialist - "
    "you cannot act on a specialist you did not start.";
function requireRunId(runId: string): string | null {
    const trimmed = (runId ?? "").trim();
    return trimmed === "" ? null : trimmed;
}

export async function answerSpecialist(
    runId: string,
    options: { approved: boolean; reason?: string; steer?: string },
): Promise<SpecialistRun> {
    // A step, for the same reason as start: answering releases a real write in
    // the Python side. Recorded as a step, a replay reuses the recorded decision
    // rather than approving the same write twice.
    "use step";
    const target = requireRunId(runId);
    if (target === null) {
        return {
            runId: "",
            token: "",
            agentName: "",
            model: "",
            error: requireRunIdMessage};
    }
    const answered = await callBackend(`/api/workflow/chat/${target}/approval`, {
        method: "POST",
        body: JSON.stringify({
            decision: options.approved ? "approved" : "rejected",
            reason: options.reason,
            steer: options.steer})});
    return {
        runId: String(answered.run_id ?? ""),
        token: String(answered.token ?? ""),
        agentName: String(answered.agent_name ?? ""),
        // The approval route starts the follow-up run and reports the model
        // that run got, so a resumed specialist stays announced consistently.
        model: String(answered.model ?? "")};
}

/** Send the user's instruction to a specialist's turn. */
export async function steerSpecialist(
    runId: string,
    text: string,
): Promise<{ runId: string; delivered: boolean; error?: string }> {
    // A step: a steer is stored state on the Python side, and an unrecorded
    // re-execution would deliver the same instruction twice.
    "use step";
    const target = requireRunId(runId);
    if (target === null) {
        return {runId: "", delivered: false, error: requireRunIdMessage};
    }
    const steered = await callBackend(`/api/workflow/chat/${target}/steer`, {
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
): Promise<{ stopped: boolean; how: string; error?: string }> {
    // A step: stopping is idempotent at the backend, but recording the call keeps
    // the turn's history honest about what it did.
    "use step";
    const target = requireRunId(runId);
    if (target === null) {
        return {stopped: false, how: "", error: requireRunIdMessage};
    }
    const stopped = await callBackend(`/api/workflow/chat/${target}/stop`, {
        method: "POST",
        body: JSON.stringify({ reason })});
    return {
        stopped: Boolean(stopped.stopped),
        how: String(stopped.how ?? "unknown")};
}
