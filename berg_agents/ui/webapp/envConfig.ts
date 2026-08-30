import { loadEnvConfig } from '@next/env'

const projectDir = process.cwd()
loadEnvConfig(projectDir)

export default async () => {
  const projectDir = process.cwd()
  loadEnvConfig(projectDir)
}

export const BuildAgentProxy = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? window.location.origin : "http://localhost:8001");

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

export async function apiFetch(path: string, options = {}) {
    const url = `${API_BASE}${path}`;
    return fetch(url, options);
}
