/*
 * Agents Server Component — fetches agent list on the server.
 * Demonstrates Next.js Server Component pattern with server-side data fetching.
 */

import { cache } from 'react';

import { apiFetch } from '@/envConfig';
import type { AgentInfo } from '@/harness/webhook';

const fetchAgents = cache(async (): Promise<AgentInfo[]> => {
  try {
    const res = await apiFetch('/api/agents');
    if (!res.ok) throw new Error('Failed to fetch agents');
    return res.json();
  } catch {
    return [];
  }
});

export default async function AgentsServer() {
  const agents = await fetchAgents();

  return (
    <div className="agents-server">
      <h2>Available Agents ({agents.length})</h2>
      {agents.map((agent) => (
        <div key={agent.name}>
          <strong>{agent.name}</strong> — {agent.model}
        </div>
      ))}
    </div>
  );
}

export { fetchAgents };
