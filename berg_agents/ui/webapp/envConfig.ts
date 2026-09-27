/**
 * Client-side environment configuration and API utilities for Next.js.
 * NEXT_PUBLIC_* variables are inlined at build time by Next.js.
 */

// Base URL for the Berg Agents Python backend server.
// NOTE: this app is a static export with no Next.js API routes,
// so same-origin can never serve the API — always default to the
// backend's own origin unless explicitly overridden.
export const BuildAgentProxy =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";

// API base path or host for REST requests (same backend default:
// this app has no same-origin API routes to fall back to).
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";

/**
 * Helper to perform fetch requests against the Berg Agents API.
 * Automatically prepends API_BASE to relative paths.
 *
 * @param path - The endpoint path (e.g. "/providers")
 * @param options - Standard fetch options (method, headers, body, etc.)
 * @returns Fetch Promise with response
 */
export async function apiFetch(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  return fetch(url, options);
}

export default BuildAgentProxy;
