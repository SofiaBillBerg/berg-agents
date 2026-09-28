/**
 * Server Actions: Provider management for LLM switching.
 * Uses Next.js App Router Server Actions for secure, server-side API calls.
 */

import { apiFetch } from '@/envConfig';

export interface SwitchProviderResult {
  success: boolean;
  error?: string;
}

/**
 * Switch the active LLM provider and model.
 * Server Action — runs on the server, never exposes API keys to the client.
 */
export async function switchProvider(
  provider: string,
  model: string,
): Promise<SwitchProviderResult> {
  'use server';

  try {
    const response = await apiFetch('/api/providers/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    });

    if (!response.ok) {
      return { success: false, error: `HTTP ${response.status}` };
    }

    return { success: true };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Fetch available providers and current selection.
 * Server Action — safe to call from client components.
 */
export async function getProviders() {
  'use server';

  try {
    const response = await apiFetch('/api/providers');
    if (!response.ok) throw new Error('Failed to fetch providers');
    return response.json();
  } catch (error) {
    console.error('Error fetching providers:', error);
    return { providers: [] };
  }
}
