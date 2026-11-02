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

/* AgentSelector - pick the active agent for the chat session.
 *
 * Mirrors ProviderSelector: fetches the agent list + the active selection,
 * and PUTs the choice to /api/agents/active so the next chat turn routes
 * to that agent (the chat agent adopts its persona). The selection is
 * also persisted on the backend session, so the Agents page and the
 * header agree.
 */

"use client";

import {useCallback, useEffect, useState} from "react";

import {API_BASE} from "@/envConfig";

interface AgentItem {
    name: string;
    description?: string;
}

/** AgentSelector - header control for the active agent. */
export default function AgentSelector() {
    const [agents, setAgents] = useState<AgentItem[]>([]);
    const [active, setActive] = useState<string | null>(null);

    const fetchAll = useCallback(async () => {
        try {
            const [listRes, activeRes] = await Promise.all([
                fetch(`${API_BASE}/api/agents`),
                fetch(`${API_BASE}/api/agents/active`)]);
            if (listRes.ok) {
                const data = await listRes.json();
                setAgents(Array.isArray(data) ? data : data.agents || []);
            }
            if (activeRes.ok) {
                const data = await activeRes.json();
                setActive(typeof data?.agent === "string" ? data.agent : null);
            }
        } catch {
            // Backend unreachable - keep the current selection in memory.
        }
    }, []);

    useEffect(() => {
        void fetchAll();
    }, [fetchAll]);

    /** Set the active agent on the backend (and locally). */
    const onChange = (name: string) => {
        const next = name === "" ? null : name;
        setActive(next);
        void fetch(`${API_BASE}/api/agents/active`, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({agent: next})}).catch(() => undefined);
    };

    return (
        <select
            aria-label="Active agent"
            className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            id="active-agent"
            name="active-agent"
            title={
                active
                    ? `Active agent: ${active} - next message routes to it`
                    : "Default chat agent"
            }
            value={active ?? ""}
            onChange={(e) => onChange(e.target.value)}
        >
            <option value="">Default chat agent</option>
            {agents.map((a) => (
                <option key={a.name} value={a.name}>
                    {a.name}
                </option>
            ))}
        </select>
    );
}
