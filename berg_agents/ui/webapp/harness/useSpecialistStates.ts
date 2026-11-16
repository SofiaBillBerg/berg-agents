import {useEffect, useState} from "react";

/**
 * The live state of a set of specialists, polled.
 *
 * Why this exists: a delegated specialist used to be invisible until the
 * orchestrator chose to look — and it usually did not, so the user sat with a
 * finished (or parked, or stuck) specialist and no way to tell which. The
 * orchestrator's willingness to poll is model behaviour; this is not. The page
 * watches its own specialists, so the state on screen is a fact rather than a
 * promise by a small model.
 *
 * Polling, not streaming: the question here is "does it need me yet", which
 * changes a handful of times during a run, and each answer is one small GET the
 * backend already answers (`/api/workflow/chat/{id}/state`). A stream per
 * specialist would be a second subscription for the same handful of facts.
 *
 * @param runIds - The runs to watch. An empty list polls nothing.
 * @returns Each run's latest state, keyed by run id; absent until first read.
 */
export function useSpecialistStates(
    runIds: string[],
): Record<string, string> {
    const [states, setStates] = useState<Record<string, string>>({});

    // A stable key: the caller's array is rebuilt each render, and polling
    // should not restart because of it.
    const key = runIds.join(",");
    useEffect(() => {
        const ids = key ? key.split(",") : [];
        if (ids.length === 0) return;
        let alive = true;

        const poll = async (): Promise<void> => {
            const entries = await Promise.all(
                ids.map(async (id) => {
                    try {
                        const response = await fetch(
                            `/api/workflow/chat/${encodeURIComponent(id)}/state`,
                        );
                        if (!response.ok) return [id, "unknown"] as const;
                        const data = (await response.json()) as {
                            state?: string;
                        };
                        return [id, String(data.state ?? "unknown")] as const;
                    } catch {
                        // A failed read leaves the previous state standing: the
                        // strip degrades to the last known truth rather than
                        // blinking to "unknown" on a dropped request.
                        return [id, "unknown"] as const;
                    }
                }),
            );
            if (alive) setStates(Object.fromEntries(entries));
        };

        void poll();
        const timer = window.setInterval(() => void poll(), 3000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [key]);

    return states;
}