/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *
 * You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://gnu.org/licenses/agpl-3.0.html>.
 */

/*
 * A model that survives a workflow step boundary, on whatever wire its
 * provider speaks.
 *
 * TWO things this file exists for, and the second is the one that was broken:
 *
 * 1. SERIALIZATION. A `WorkflowAgent` runs each model call as its own step, and
 *    anything handed across that boundary is serialized. The AI SDK's providers
 *    serialize their *config*, and `serializeModelOptions` keeps only JSON
 *    values — so `baseURL` and the request `url` builder (both functions, or
 *    behind one) are dropped, and a deserialized `openai-compatible` model
 *    throws `this.config.url is not a function` on its first call. Verified
 *    2026-11-12 by round-tripping both `@ai-sdk/openai` and
 *    `@ai-sdk/openai-compatible`. The documented fix is
 *    `WORKFLOW_SERIALIZE` / `WORKFLOW_DESERIALIZE` carrying plain strings and
 *    rebuilding the working model on the far side, which is what this class is.
 *
 * 2. THE WIRE. It used to be called `LocalModel` and to hardcode berg's own
 *    Ollama as its endpoint, so the orchestrator ran on bonsai-2:9b no matter
 *    which model was picked in the UI — even an Ollama one, because the
 *    fallback was silent. The endpoint and the wire now come from berg's
 *    configuration through `GET /api/providers/resolve`, which is the SAME
 *    resolver `berg_agents/providers/models.py::resolve_model_instance` uses
 *    for every Python agent: one rule for which provider owns a model, which
 *    URL serves it, and whether it speaks Anthropic Messages or OpenAI Chat
 *    Completions. Nothing here guesses.
 *
 * That resolver is the reason the Anthropic branch exists at all: a provider
 * block declaring `"api": "anthropic-messages"` is served by
 * `@ai-sdk/anthropic`, because the two wires are not interchangeable — sending
 * Messages-shaped traffic to a Chat Completions client produces a 404.
 */

import { createAnthropic } from "@ai-sdk/anthropic";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import {
  WORKFLOW_DESERIALIZE,
  WORKFLOW_SERIALIZE} from "@ai-sdk/provider-utils";

/** What a model needs to carry across a step: plain data, and nothing else. */
export interface ModelSpec {
  /** The model name at the endpoint, e.g. `ssfdre38/gemma4-turbo:latest`. */
  modelId: string;
  /** The endpoint's base URL, from berg's provider configuration. */
  baseURL: string;
  /** The key the endpoint expects; empty for a keyless local one. */
  apiKey: string;
  /** The provider's name, which shows up in errors and telemetry. */
  provider: string;
  /**
   * The wire, from the provider block's `"api"` option:
   * `anthropic-messages` for Anthropic's Messages API, anything else for
   * OpenAI Chat Completions.
   */
  api: string;
  /**
   * The provider block's declared request timeout, in MILLISECONDS — the AI
   * SDK's convention, and the unit berg's configuration file follows. Absent
   * means no override, and the provider's own default applies.
   *
   * It is carried rather than dropped on purpose: a provider block that
   * declares one is saying "wait this long, no longer", and silently
   * discarding that leaves a hung endpoint hanging for the SDK's default
   * instead. The Python resolver applies the same declaration to its own
   * model instances, so both sides of the language boundary honour it.
   */
  timeoutMs?: number;
}

/** The provider-block values that mean "speaks Anthropic Messages". */
const ANTHROPIC_APIS = new Set(["anthropic-messages", "anthropic"]);

/**
 * A language model bound to a berg-configured endpoint.
 *
 * It delegates every call to a freshly built provider model, so the provider's
 * own request building, streaming and tool handling all still apply — this
 * class adds serialization and wire selection, it does not reimplement a
 * provider.
 */
export class BergModel {
  /** Required by the AI SDK's model contract. */
  readonly specificationVersion = "v4" as const;
  /** Which provider this model claims, for errors and telemetry. */
  readonly provider: string;
  /** The model name at the endpoint. */
  readonly modelId: string;

  /** The endpoint this model talks to. */
  private readonly baseURL: string;
  /** The key the endpoint expects. */
  private readonly apiKey: string;
  /** The wire this endpoint speaks. */
  private readonly api: string;
  /** The declared request timeout, in milliseconds, when there is one. */
  private readonly timeoutMs?: number;

  /**
   * @param spec - The resolved endpoint, wire and name.
   */
  constructor(spec: ModelSpec) {
    this.provider = spec.provider;
    this.modelId = spec.modelId;
    this.baseURL = spec.baseURL;
    this.apiKey = spec.apiKey;
    this.api = spec.api;
    // Only a positive number is a timeout. Zero or a negative one is a
    // configuration mistake that must not become "fail every request
    // immediately", so it is treated as absent and the provider's own default
    // applies.
    this.timeoutMs =
      typeof spec.timeoutMs === "number" &&
      Number.isFinite(spec.timeoutMs) &&
      spec.timeoutMs > 0
        ? spec.timeoutMs
        : undefined;
  }

  /**
   * Reduce to what can cross a step boundary: plain data only.
   *
   * @param model - The model being serialized.
   * @returns Its endpoint, wire and name as JSON-safe data.
   */
  static [WORKFLOW_SERIALIZE](model: BergModel): ModelSpec {
    return {
      modelId: model.modelId,
      baseURL: model.baseURL,
      apiKey: model.apiKey,
      provider: model.provider,
      api: model.api,
      timeoutMs: model.timeoutMs};
  }

  /**
   * Rebuild a working model from serialized state.
   *
   * @param spec - What {@link WORKFLOW_SERIALIZE} produced.
   * @returns A model that can actually make the call.
   */
  static [WORKFLOW_DESERIALIZE](spec: ModelSpec): BergModel {
    return new BergModel(spec);
  }

  /**
   * Whether this endpoint speaks Anthropic's Messages API.
   *
   * @returns True when the provider block declares it.
   */
  private get isAnthropic(): boolean {
    return ANTHROPIC_APIS.has(this.api.trim().toLowerCase());
  }

  /**
   * The base URL for an Anthropic client, with the path suffix it appends
   * itself stripped.
   *
   * The Anthropic SDK always appends `/v1/messages`, so a configured base URL
   * that already carries it — the full endpoint path, as one naturally pastes
   * it — would double up. This mirrors exactly what
   * `resolve_model_instance` does on the Python side, so the two sides of the
   * boundary agree on the same configured value.
   *
   * @returns The root the Anthropic client should be built with.
   */
  private anthropicBaseURL(): string {
    let root = this.baseURL.trim().replace(/\/+$/, "");
    for (const suffix of ["/v1/messages", "/messages"]) {
      if (root.endsWith(suffix)) {
        root = root.slice(0, -suffix.length) || "/";
        break;
      }
    }
    return root;
  }

  /**
   * The provider's fetch, bounded by the declared timeout.
   *
   * Both wires accept a `fetch` override, and a signal is the whole override
   * needs: the request is aborted once the declared window closes. This is an
   * approximation rather than the equivalent of the per-phase timeouts the
   * Python side builds through its HTTP client — one window for the whole
   * request, rather than separate connect and read windows — and it is
   * recorded as such rather than presented as more than it is.
   *
   * @returns The fetch to install, or undefined to install none.
   */
  private boundedFetch(): typeof globalThis.fetch | undefined {
    const ms = this.timeoutMs;
    if (!ms) return undefined;
    return (input, init) =>
      globalThis.fetch(input, {
        ...init,
        signal: init?.signal ?? AbortSignal.timeout(ms)});
  }

  /** The provider model for this wire, rebuilt from the strings above. */
  private inner() {
    // Built per call rather than cached: a deserialized instance has no usable
    // config of its own, so reconstructing is what makes the model work on the
    // far side of the step boundary.
    const fetch = this.boundedFetch();
    if (this.isAnthropic) {
      return createAnthropic({
        apiKey: this.apiKey || undefined,
        baseURL: this.anthropicBaseURL(),
        ...(fetch ? { fetch } : {})})(this.modelId);
    }
    return createOpenAICompatible({
      name: this.provider,
      baseURL: this.baseURL,
      apiKey: this.apiKey,
      ...(fetch ? { fetch } : {})})(this.modelId);
  }

  /** Which URLs the endpoint can fetch itself, delegated to the provider. */
  get supportedUrls() {
    return this.inner().supportedUrls;
  }

  /**
   * Non-streaming generation, delegated.
   *
   * @param options - The AI SDK's call options.
   * @returns The provider's generation result.
   */
  async doGenerate(
    options: Parameters<ReturnType<BergModel["inner"]>["doGenerate"]>[0],
  ) {
    return this.inner().doGenerate(options);
  }

  /**
   * Streaming generation, the path the agent actually uses.
   *
   * @param options - The AI SDK's call options.
   * @returns The provider's stream result.
   */
  async doStream(
    options: Parameters<ReturnType<BergModel["inner"]>["doStream"]>[0],
  ) {
    return this.inner().doStream(options);
  }
}

/**
 * Build a model from a resolved spec.
 *
 * No defaults and no fallback: a caller that passes a spec with no endpoint
 * gets a model that fails its call with that fact visible, rather than one
 * that quietly talks to a different machine. The silent Ollama fallback is
 * precisely the defect this replaces.
 *
 * @param spec - What `GET /api/providers/resolve` answered.
 * @returns A model that can cross a workflow step boundary intact.
 */
export function bergModel(spec: ModelSpec): BergModel {
  return new BergModel(spec);
}
