/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
 *
 * Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
 *
 * This program is free software: you can redistribute it and/or modify
 *
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



/**
 * Provider Actions: Client-side action layer for LLM provider management.
 *
 * Current: Uses apiFetch for API calls (works with static export).
 * Future: Can be upgraded to true Server Actions when the project moves
 *         off static export ('use server' at module level).
 *
 * This layer provides:
 * - Combined data fetching (providers + active in one round-trip)
 * - Validation of provider/model pairs
 * - Centralized error handling
 */

import {apiFetch} from "@/envConfig";

export interface ProviderItem {
  name: string;
  model: string;
}

export interface ActiveProviderState {
  provider: string;
  model: string;
}

export interface SwitchProviderResult {
  success: boolean;
  error?: string;
  active?: ActiveProviderState;
}

export interface ProviderData {
  providers: ProviderItem[];
  active: ActiveProviderState | null;
}

/**
 * Switch the active LLM provider and model.
 * Calls the backend API via apiFetch - in production this hits the FastAPI
 * proxy endpoint; in dev mode it can be upgraded to a true Server Action.
 */
export async function switchProvider(
  provider: string,
  model: string,
): Promise<SwitchProviderResult> {
  try {
    const response = await apiFetch("/api/providers/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model })});

    if (!response.ok) {
      return { success: false, error: `HTTP ${response.status}` };
    }

    return {
      success: true,
      active: { provider, model }};
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error"};
  }
}

/**
 * Fetch available providers.
 * Returns provider list from the backend API.
 */
export async function getProviders(): Promise<{ providers: ProviderItem[] }> {
  try {
    const response = await apiFetch("/api/providers");
    if (!response.ok) throw new Error("Failed to fetch providers");
    return response.json();
  } catch (error) {
    console.error("Error fetching providers:", error);
    return { providers: [] };
  }
}

/**
 * Fetch both providers list and active provider in one combined round-trip.
 * Reduces client-side waterfall requests vs fetching separately.
 */
export async function getProviderData(): Promise<ProviderData> {
  try {
    const [listRes, activeRes] = await Promise.all([
      apiFetch("/api/providers"),
      apiFetch("/api/providers/active")]);

    let providers: ProviderItem[] = [];
    if (listRes.ok) {
      const listData = await listRes.json();
      if (listData.providers && Array.isArray(listData.providers)) {
        providers = listData.providers;
      }
    }

    let active: ActiveProviderState | null = null;
    if (activeRes.ok) {
      const activeData = await activeRes.json();
      if (activeData.provider && activeData.model) {
        active = { provider: activeData.provider, model: activeData.model };
      }
    }

    return { providers, active };
  } catch (error) {
    console.error("Error fetching provider data:", error);
    return { providers: [], active: null };
  }
}

/**
 * Check if a provider/model pair is valid and get recommended alternatives.
 * Validation happens server-side via the backend API.
 */
export async function validateProvider(
  provider: string,
  model: string,
): Promise<{ valid: boolean; alternatives: ProviderItem[] }> {
  try {
    const response = await apiFetch("/api/providers");
    if (!response.ok) {
      return { valid: false, alternatives: [] };
    }

    const data = await response.json();
    const allProviders: ProviderItem[] = data.providers || [];
    const isValid = allProviders.some(
      (p) => p.name === provider && p.model === model,
    );
    const alternatives = allProviders
      .filter((p) => p.name === provider && p.model !== model)
      .slice(0, 5);

    return { valid: isValid, alternatives };
  } catch (error) {
    console.error("Error validating provider:", error);
    return { valid: false, alternatives: [] };
  }
}
