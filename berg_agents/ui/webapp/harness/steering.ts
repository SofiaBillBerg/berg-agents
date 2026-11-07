/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

/*
 * Steering - messages the agent has not read yet.
 *
 * A message typed while a run is going is queued on the server's run, so
 * it exists in the conversation the browser cannot show: it is in the
 * model's inbox, not in the transcript. This is the client's view of that
 * inbox, and it is SAMPED rather than derived from optimistic sends,
 * because the server owns the answer - a guess would show the strip for
 * a message the model already consumed, or hide one it had not.
 *
 * The strip is only ever non-empty inside a live run, so the poll runs
 * only while one is streaming; the emptiness outside a run is the state,
 * not a gap.
 */

import {useEffect, useState} from "react";

/** What the hook needs from the chat hook's own render. */
export interface UsePendingSteeringDeps {
    /** Active session id, or null when none is adopted yet. */
    sessionId: string | null;
    /** Whether a run is streaming right now. */
    isStreaming: boolean;
    /** Base URL of the Berg Agents API. */
    apiBase: string;
}

/** The steering strip's contents. */
export interface PendingSteering {
    /** Texts queued on the run that the model has not read yet. */
    pendingSteering: string[];
    /** Clear the strip (a run that ended has nothing left to read). */
    setPendingSteering: (texts: string[]) => void;
}

/**
 * Sample the server for steering messages the model has not read.
 *
 * @param deps - Session, streaming state and API base.
 * @returns The strip's contents and its setter (the run watcher clears
 *     it when the run it belonged to ends).
 */
export function usePendingSteering(
    deps: UsePendingSteeringDeps,
): PendingSteering {
    const {sessionId, isStreaming, apiBase} = deps;
    const [pendingSteering, setPendingSteering] = useState<string[]>([]);
    useEffect(() => {
        if (!sessionId) {
            setPendingSteering([]);
            return;
        }
        let cancelled = false;
        const poll = async () => {
            try {
                const resp = await fetch(
                    `${apiBase}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                );
                if (!resp.ok || cancelled) return;
                const data = (await resp.json()) as {
                    live?: unknown;
                    steering?: unknown;
                };
                // The strip means "the agent is about to read this". Once the
                // run is over nothing will be read in this turn, so the strip
                // empties rather than outliving the run that gave it meaning.
                const queued =
                    data.live === true && Array.isArray(data.steering)
                        ? data.steering.filter((t): t is string => typeof t === "string")
                        : [];
                if (!cancelled) setPendingSteering(queued);
            } catch {
                // Backend unreachable - keep showing what we know.
            }
        };
        void poll();
        // Nothing to poll when no run is live; the strip is only ever
        // non-empty inside a run.
        if (!isStreaming)
            return () => {
                cancelled = true;
            };
        const timer = setInterval(() => void poll(), 1200);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [sessionId, isStreaming, apiBase]);

    return {pendingSteering, setPendingSteering};
}
