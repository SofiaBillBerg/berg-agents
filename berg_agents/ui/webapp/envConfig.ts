/**
 * Client-side environment configuration and API utilities for Next.js.
 * NEXT_PUBLIC_* variables are inlined at build time by Next.js.
 */

// Base URL for the Berg Agents Python backend server.
// Empty means same-origin: FastAPI serves this static export and the
// /api/* routes from one origin on whatever port it runs on, so
// relative URLs work on any port with no build-time coupling.
// (NEXT_PUBLIC_* values are inlined into the JS bundle at build time,
// so a hardcoded fallback like http://localhost:8001 would break every
// run on another port.) Only set NEXT_PUBLIC_API_BASE_URL when the
// frontend is served separately (e.g. `next dev` on :3000 talking to a
// backend port).
export const BuildAgentProxy = process.env.NEXT_PUBLIC_API_BASE_URL || "";

// API base path or host for REST requests. Empty means same-origin:
// the FastAPI backend serves this static export and the /api/* routes
// from one origin on any port, so relative URLs just work.
//
// DEV NOTE (`next dev` on :3000): the dev server has no /api routes,
// so set NEXT_PUBLIC_API_BASE_URL=http://localhost:<backend-port> when
// running the frontend standalone, e.g.
// NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 bun run next dev
export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL || ""
).replace(/\/+$/, "");

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
