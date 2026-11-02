/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
 * The system follows a harness-based execution model with multiple specialized agents working together.
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

import React from "react";

/** Props for the steering strip. */
export interface SteeringStripProps {
    /**
     * Messages the agent has NOT read yet, in the order they were sent.
     * The list comes from the server, which owns the run, so an entry here
     * is genuinely unread. An empty list renders nothing.
     */
    messages: string[];
}

/**
 * SteeringStrip - the unread break between the user and the agent.
 *
 * A message typed while the agent works steers it; it reaches the model at
 * the agent's next step. Until then it belongs HERE, not in the transcript,
 * because the transcript shows what the agent has actually seen. Once the
 * model receives it, the server reports it consumed and the message appears
 * in the transcript at its real position - never in both places at once.
 *
 * Rendered directly above the input bar so it reads as "this is still on its
 * way", not as something already said and answered.
 */
export default function SteeringStrip({messages}: SteeringStripProps) {
    if (messages.length === 0) return null;

    return (
        <div
            aria-label="Steering messages the agent has not read yet"
            aria-live="polite"
            className="mx-1 mb-1 flex flex-col gap-1"
            role="status"
        >
            {messages.map((text, index) => (
                <div
                    key={`${index}-${text.slice(0, 24)}`}
                    className="flex items-start gap-2 rounded-md border border-dashed border-warning/50 bg-warning/10 px-3 py-1.5 text-sm"
                >
                    <span
                        className="mt-px shrink-0 text-[11px] font-medium uppercase tracking-wide text-warning"
                        title="The agent has not read this yet"
                    >
                        queued
                    </span>
                    <span className="min-w-0 whitespace-pre-wrap break-words opacity-90">
                        {text}
                    </span>
                </div>
            ))}
        </div>
    );
}
