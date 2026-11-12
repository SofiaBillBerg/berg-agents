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
 * A model for berg's own endpoint that survives a workflow step boundary.
 *
 * Why this exists at all: a `WorkflowAgent` runs each model call as its own
 * step, and anything handed across that boundary is serialized. The AI SDK's
 * providers serialize their *config*, and `serializeModelOptions` keeps only
 * JSON values — so `baseURL` and the request `url` builder (both functions, or
 * behind one) are dropped. A deserialized `openai-compatible` model therefore
 * throws `this.config.url is not a function` on its first call.
 *
 * Verified, not assumed (2026-11-12): round-tripping both `@ai-sdk/openai` and
 * `@ai-sdk/openai-compatible` models loses `baseURL`/`url` and breaks the call.
 *
 * The fix is the one the AI SDK documents for custom providers: implement
 * `WORKFLOW_SERIALIZE` / `WORKFLOW_DESERIALIZE` and store only plain strings,
 * rebuilding the working model from them on the other side. Because the
 * endpoint is rebuilt from `baseURL` each time, this also keeps berg pointed at
 * its own ollama rather than at a hosted gateway — which is the point.
 */

import {createOpenAICompatible} from "@ai-sdk/openai-compatible";
import {
    WORKFLOW_DESERIALIZE,
    WORKFLOW_SERIALIZE} from "@ai-sdk/provider-utils";

/** What a model needs to carry across a step: strings, and nothing else. */
interface LocalModelState {
    /** The model name at the endpoint, e.g. `bonsai-2:9b`. */
    modelId: string;
    /** The OpenAI-compatible base URL, e.g. `http://127.0.0.1:11434/v1`. */
    baseURL: string;
    /** The key the endpoint expects; ollama accepts any non-empty value. */
    apiKey: string;
    /** The provider name, which shows up in error messages and telemetry. */
    provider: string;
}

/**
 * A language model bound to berg's local OpenAI-compatible endpoint.
 *
 * It delegates every call to a freshly built `openai-compatible` model, so the
 * provider's own request building, streaming and tool handling all still apply —
 * this class adds serialization, it does not reimplement a provider.
 */
export class LocalModel {
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

    /**
     * @param state - The strings that identify the endpoint and model.
     */
    constructor(state: LocalModelState) {
        this.provider = state.provider;
        this.modelId = state.modelId;
        this.baseURL = state.baseURL;
        this.apiKey = state.apiKey;
    }

    /**
     * Reduce the model to what can cross a step boundary.
     *
     * Only strings, deliberately: this is the hook whose absence caused the
     * `this.config.url is not a function` failure, so the state must stay
     * plain data rather than a provider config.
     *
     * @param model - The model being serialized.
     * @returns Its endpoint and name, as plain JSON.
     */
    static [WORKFLOW_SERIALIZE](model: LocalModel): LocalModelState {
        return {
            modelId: model.modelId,
            baseURL: model.baseURL,
            apiKey: model.apiKey,
            provider: model.provider};
    }

    /**
     * Rebuild a working model from serialized state.
     *
     * @param state - What {@link WORKFLOW_SERIALIZE} produced.
     * @returns A model that can actually make the call.
     */
    static [WORKFLOW_DESERIALIZE](state: LocalModelState): LocalModel {
        return new LocalModel(state);
    }

    /**
     * The provider, rebuilt on demand.
     *
     * Built per call rather than cached because a deserialized instance has no
     * usable config of its own — reconstructing is what makes the model work on
     * the far side of the step boundary.
     *
     * @returns An `openai-compatible` provider bound to this endpoint.
     */
    private providerInstance() {
        return createOpenAICompatible({
            name: this.provider,
            baseURL: this.baseURL,
            apiKey: this.apiKey});
    }

    /** The underlying provider model, rebuilt from strings. */
    private inner() {
        return this.providerInstance()(this.modelId);
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
    async doGenerate(options: Parameters<ReturnType<LocalModel["inner"]>["doGenerate"]>[0]) {
        return this.inner().doGenerate(options);
    }

    /**
     * Streaming generation, delegated.
     *
     * @param options - The AI SDK's call options.
     * @returns The provider's stream result.
     */
    async doStream(options: Parameters<ReturnType<LocalModel["inner"]>["doStream"]>[0]) {
        return this.inner().doStream(options);
    }
}

/**
 * Build a model for berg's local endpoint.
 *
 * @param options - Endpoint and model name; both default to berg's own ollama.
 * @returns A model that can cross a workflow step boundary intact.
 */
export function localModel(
    options: {
        modelId?: string;
        baseURL?: string;
        apiKey?: string;
        provider?: string;
    } = {},
): LocalModel {
    return new LocalModel({
        modelId: options.modelId || process.env.ORCHESTRATOR_MODEL || "bonsai-2:9b",
        baseURL:
            options.baseURL ||
            process.env.ORCHESTRATOR_BASE_URL ||
            // berg talks to ollama on its own port; the OpenAI-compatible
            // surface lives under /v1.
            `http://127.0.0.1:${process.env.BERG_AGENT_OLLAMA_PORT || "11434"}/v1`,
        apiKey: options.apiKey || process.env.ORCHESTRATOR_API_KEY || "ollama",
        provider: options.provider || "berg-local"});
}
