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
 * Start an orchestrator turn and stream it back in the UI's own protocol.
 *
 * Two conversions happen here and nowhere else, so the wire stays one wire:
 * `start` hands the turn to the durable runtime, and
 * `createModelCallToUIChunkTransform` turns the runtime's raw model parts into
 * the `UIMessageChunk`s that berg's chat surface already renders.
 */

import { createModelCallToUIChunkTransform } from "@ai-sdk/workflow";
import { createUIMessageStreamResponse, type UIMessage } from "ai";
import { start } from "workflow/api";

import { saveTurn } from "@/lib/orchestrator-turns";
import { bergModel, type ModelSpec } from "@/harness/berg-model";
import { orchestratorTurn } from "@/workflows/orchestrator-turn";
import { backendOrigin } from "@/harness/specialists";

/**
 * Resolve the brain this turn runs on.
 *
 * Asks berg's Python backend, which owns the provider configuration in
 * `bergagents.jsonc` and the resolver every Python agent already uses. That is
 * deliberate: this app used to hardcode berg's own Ollama, so a model chosen in
 * the UI — even an Ollama one — was silently replaced by the fallback, and a
 * model on another provider could not be addressed at all. One resolver, asked
 * once per turn, means a model moves provider without this side learning a
 * second rule.
 *
 * The answer carries an `api_key` for endpoints that need one. The caller is
 * berg's own front-end server on loopback, in the same trust domain as the
 * environment that key came from — the same domain the Python agents run in.
 *
 * @param modelId - The chosen model, or empty for the configured default.
 * @returns The resolved endpoint, wire and name, as plain data the workflow
 *   boundary can carry.
 * @throws When the backend cannot resolve it, so a turn fails with the reason
 *   visible rather than quietly running somewhere else.
 */
async function resolveOrchestratorModel(modelId: string): Promise<ModelSpec> {
  const query = modelId ? `?model=${encodeURIComponent(modelId)}` : "";
  const response = await fetch(
    `${backendOrigin()}/api/providers/resolve${query}`,
  );
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(
      `Could not resolve the orchestrator's model${
        modelId ? ` (${modelId})` : ""
      }: HTTP ${response.status} ${detail}`.slice(0, 400),
    );
  }
  const resolved = (await response.json()) as {
    model?: string;
    provider?: string;
    api?: string;
    base_url?: string;
    api_key?: string;
  };
  // Mapped here, once, from the backend's own field names into this app's
  // spec: the API speaks snake_case and the model builder speaks its own
  // shape, and one translation between them is better than two.
  const spec: ModelSpec = {
    modelId: resolved.model ?? "",
    baseURL: resolved.base_url ?? "",
    apiKey: resolved.api_key ?? "",
    provider: resolved.provider ?? "",
    api: resolved.api ?? ""};
  // Never build a model without an endpoint: fail here, where the reason is
  // visible, rather than in a step where it reads as a model failure.
  if (!spec.modelId || !spec.baseURL) {
    throw new Error(
      "The backend resolved no endpoint for the orchestrator's model.",
    );
  }
  return spec;
}

/**
 * POST /api/orchestrator
 *
 * @param request - JSON body with `messages` (the UI's conversation) and an
 *   optional `model` naming the brain this turn runs on.
 * @returns A UI message stream, and the run id for reconnection.
 */
export async function POST(request: Request): Promise<Response> {
  const body = (await request.json()) as {
    messages?: UIMessage[];
    model?: string;
  };
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const spec = await resolveOrchestratorModel(body.model?.trim() ?? "");

  // The instance, not the spec: the workflow boundary serializes a model
  // through WORKFLOW_SERIALIZE, so what crosses is plain data either way, and
  // passing the built model keeps the workflow from re-deriving one.
  const run = await start(orchestratorTurn, [messages, bergModel(spec)]);

  // The conversation, recorded against the run it became. This is the only
  // moment both exist together: the run id comes back from `start`, and the
  // messages are what the UI just sent. Without it a resume has no source of
  // truth for the USER's turns — a workflow stream records only what the agent
  // wrote (see lib/orchestrator-turns.ts).
  await saveTurn(run.runId, messages);

  return createUIMessageStreamResponse({
    stream: run.readable.pipeThrough(createModelCallToUIChunkTransform()),
    // The id is what lets the client resume from where it left off instead
    // of rebuilding the turn — the reason this is a workflow at all.
    headers: { "x-workflow-run-id": run.runId }});
}
