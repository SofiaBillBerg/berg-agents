// API base URL configuration.
//
// When running the built app through the FastAPI backend (production),
// relative URLs work because the API and static files share the same origin.
//
// When running `npm run preview` or a separate dev server, set
// VITE_API_BASE_URL to the backend origin, e.g.:
//   VITE_API_BASE_URL=http://localhost:8001 npm run preview
export const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export async function apiFetch(path, options = {}) {
    const url = `${API_BASE}${path}`;
    return fetch(url, options);
}
