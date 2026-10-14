/**
 * Plugin-side API configuration, supplied by the host at runtime.
 *
 * A plugin bundle is loaded at runtime by the host (never bundled with
 * it), so it cannot read build-time `process.env` the way a normal
 * Next.js module can — the value would be frozen when the plugin was
 * built and `process` does not even exist once bundled.
 *
 * Instead the host publishes its own resolved API base on
 * `window.BergRuntime.apiBase` (see the host's app/runtime), and this
 * module reads it. That means the plugin always talks to the same
 * backend the host itself is talking to, including when the host is
 * served from a different origin than the API.
 */

/** Host runtime surface this module depends on. */
declare global {
  interface Window {
    BergRuntime?: {
      apiBase?: string;
      require?: (specifier: string) => unknown;
    };
  }
}

/**
 * API base for the plugin's own requests.
 *
 * :return The host's resolved API base, or "" for same-origin.
 */
export function apiBase(): string {
  if (typeof window === "undefined") return "";
  return String(window.BergRuntime?.apiBase ?? "");
}

/**
 * Fetch one of this plugin's endpoints through the host's API base.
 *
 * @param path - Path beginning with "/" (e.g. "/api/plugins/...").
 * @param init - Standard fetch options.
 * @returns The fetch response.
 */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${apiBase()}${path}`, init);
}
