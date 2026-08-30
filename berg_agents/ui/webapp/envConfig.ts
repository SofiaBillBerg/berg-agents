/**
 * Client-side environment configuration and API utilities for Next.js.
 * NEXT_PUBLIC_* variables are inlined at build time by Next.js.
 */

// Base URL for the Berg Agents Python backend server
export const BuildAgentProxy =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.origin
    : "http://localhost:8001");

// API base path or host for REST requests
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

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
