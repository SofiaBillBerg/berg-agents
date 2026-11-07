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
 * The session this chat belongs to - its identity, and every way it changes.
 *
 * The server owns the conversation; this hook owns the client's handle on
 * it: which session is open, its title, and the four ways that handle
 * moves (mount restore, open by id, reload from the server, start a new
 * one). All four converge on restoreMessages, the one function that puts
 * server messages into the live chat, so there is one place where a
 * stored snapshot becomes UI state.
 *
 * It is called BEFORE the chat hook's `useChat`, because the transport
 * inside it reads the session ref and adopts the id the server mints on
 * the first send. That is also why the title re-read effect (which needs
 * to know whether a run is streaming) stays in the chat hook: its
 * dependency does not exist yet at this point in the render.
 */

import type {UIMessage} from "ai";

import {useCallback, useEffect, useRef, useState} from "react";

import {sanitizeHistory} from "./history";
import {
    forgetStoredSessionId,
    readStoredSessionId,
    storeSessionId} from "./sessionIdentity";

/** What the hook needs from the chat hook's own render. */
export interface UseServerSessionsDeps {
    /** Base URL of the Berg Agents API. */
    apiBase: string;
    /** The SDK's message setter - how restored messages enter the chat. */
    setUIMessages: (messages: UIMessage[]) => void;
}

/** The session handle and the four ways it changes. */
export interface ServerSessions {
    /** Active server-side session id, or null before one is adopted. */
    sessionId: string | null;
    /** Active session title for the chrome row. */
    sessionTitle: string | null;
    /** Set the title (the chat hook re-reads it after a settled turn). */
    setSessionTitle: (title: string | null) => void;
    /** Read the current id without re-subscribing (Stop, transport). */
    sessionIdRef: React.MutableRefObject<string | null>;
    /** Set the id and its ref together - never one without the other. */
    adoptSession: (id: string | null) => void;
    /** Put server messages into the live chat (dedupes ids). */
    restoreMessages: (
        msgs: unknown[],
        sessionId?: string | null,
    ) => Promise<void>;
    /** Replace the transcript with the server's saved copy.
        (The data is returned for callers that need the session record;
        none of them read it today, so it stays untyped on purpose.) */
    reloadSession: (id: string) => Promise<unknown>;
    /** Open a session by id: load it, adopt it, remember it. */
    openSession: (id: string) => Promise<void>;
    /** Start a new server-side session (numbered title from the backend). */
    newServerChat: () => Promise<void>;
}

/**
 * Own the session this chat belongs to.
 *
 * @param deps - The API base and the SDK's message setter.
 * @returns The session handle and its four transitions.
 */
export function useServerSessions(
    deps: UseServerSessionsDeps,
): ServerSessions {
    const {apiBase, setUIMessages} = deps;

    // Server-side session: the authoritative conversation record shared
    // by every browser. Declared before useChat so the transport body
    // below always carries the current id.
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [sessionTitle, setSessionTitle] = useState<string | null>(null);

    // Callbacks that fire outside React's render (Stop, follow, reconnect)
    // need the current session id without re-subscribing on every session
    // switch. It is written by `adoptSession` at the same moment as the
    // state, never by a later effect: a Stop clicked right after a session
    // switch would otherwise address the previous session's run.
    const sessionIdRef = useRef<string | null>(null);
    const adoptSession = useCallback((id: string | null) => {
        sessionIdRef.current = id;
        setSessionId(id);
    }, []);

    // Restore server-session messages into the live chat.
    // A stored snapshot does NOT imply no live run: a reload while the run
    // is paused on an approval restores exactly that. Expiring the pending
    // approval then leaves a paused run the browser can never answer - the
    // card has no Approve button and the turn is wedged. So the server is
    // asked first, and a live pause preserves the approval.
    // Duplicate message ids (e.g. one request dumped to two UI messages)
    // are suffixed — React keys must be unique and ids are otherwise opaque.
    const restoreMessages = useCallback(
        async (msgs: unknown[], sessionId?: string | null) => {
            if (!Array.isArray(msgs)) return;
            let paused = false;
            if (sessionId) {
                try {
                    const resp = await fetch(
                        `${apiBase}/api/chat/status?session=${encodeURIComponent(sessionId)}`,
                    );
                    if (resp.ok) {
                        const state = await resp.json();
                        paused = state?.outcome === "paused";
                    }
                } catch {
                    // Status unreachable: fall back to the conservative
                    // "no live run" assumption rather than blocking restore.
                }
            }
            const clean = sanitizeHistory(msgs, paused) as unknown as Array<{
                id?: unknown;
            }>;
            const seen = new Set<string>();
            for (const m of clean) {
                if (
                    typeof m !== "object" ||
                    m === null ||
                    typeof m.id !== "string"
                ) {
                    continue;
                }
                let id: string = m.id;
                if (seen.has(id)) {
                    let n = 2;
                    while (seen.has(`${id}-dup${n}`)) n += 1;
                    id = `${id}-dup${n}`;
                    m.id = id;
                }
                seen.add(id);
            }
            setUIMessages(clean as unknown as UIMessage[]);
        },
        [apiBase, setUIMessages],
    );

    // Replace the transcript with the server's saved copy of a session.
    // The server owns the conversation, so this is what any client shows
    // once it has stopped following a run: the turn exactly as saved.
    const reloadSession = useCallback(
        async (id: string) => {
            const resp = await fetch(
                `${apiBase}/api/sessions/${encodeURIComponent(id)}`,
            );
            if (!resp.ok) throw new Error(`Session ${id}: HTTP ${resp.status}`);
            const data = await resp.json();
            await restoreMessages(
                Array.isArray(data.messages) ? data.messages : [],
                id,
            );
            return data;
        },
        [apiBase, restoreMessages],
    );

    // Open a server-side session: load its transcript, adopt its id.
    const openSession = async (id: string) => {
        const data = await reloadSession(id);
        adoptSession(id);
        if (data.session && typeof data.session.title === "string") {
            setSessionTitle(data.session.title);
        }
        storeSessionId(id);
    };

    // Start a new server-side session (numbered title from the backend).
    const newServerChat = async () => {
        const resp = await fetch(`${apiBase}/api/sessions`, {method: "POST"});
        if (!resp.ok) throw new Error(`New session: HTTP ${resp.status}`);
        const data = await resp.json();
        setUIMessages([]);
        adoptSession(typeof data.id === "string" ? data.id : null);
        setSessionTitle(typeof data.title === "string" ? data.title : null);
        if (typeof data.id === "string") {
            storeSessionId(data.id);
        }
    };

    // Restore the persisted conversation once, after mount. Server
    // first (shared across browsers), localStorage as offline fallback.
    // With no stored session id, adopt the project's active session when
    // one exists, so every window converges on the same conversation.
    // With none, the page holds NO id at all and the first send carries
    // an empty one — the server mints the canonical, project-suffixed id.
    // A client-side id is the one place a second id format could reappear,
    // so there is none.
    useEffect(() => {
        let cancelled = false;
        const restore = async () => {
            try {
                const storedId = readStoredSessionId();
                if (storedId) {
                    try {
                        const resp = await fetch(
                            `${apiBase}/api/sessions/${encodeURIComponent(storedId)}`,
                        );
                        if (resp.ok && !cancelled) {
                            const data = await resp.json();
                            if (
                                Array.isArray(data.messages) &&
                                data.messages.length > 0
                            ) {
                                await restoreMessages(data.messages, storedId);
                            }
                            adoptSession(storedId);
                            if (
                                data.session &&
                                typeof data.session.title === "string"
                            ) {
                                setSessionTitle(data.session.title);
                            }
                            return;
                        }
                        if (resp.status === 404) {
                            // The stored session is gone (deleted
                            // server-side). Forget it rather than retrying
                            // a dead id on every mount - and so a later
                            // send never resurrects it through the lazy
                            // row-create on first message.
                            forgetStoredSessionId();
                        }
                    } catch {
                        // Server unreachable - fall through to the
                        // project's active session.
                    }
                } else {
                    // No session yet: adopt the project's active session
                    // when one exists, so every window converges on the
                    // same conversation. With none, the first send mints.
                    try {
                        const currentResp = await fetch(
                            `${apiBase}/api/sessions/current`,
                        );
                        if (currentResp.ok && !cancelled) {
                            const current = await currentResp.json();
                            if (typeof current.id === "string" && current.id) {
                                await openSession(current.id);
                                return;
                            }
                        }
                    } catch {
                        // Server unreachable - the first send retries.
                    }
                }
            } finally {
                // No local copy: the server session is the only source.
            }
        };
        void restore();
        return () => {
            cancelled = true;
        };
        // Runs once on mount: a re-run would re-restore over a live chat.
         
    }, []);

    return {
        sessionId,
        sessionTitle,
        setSessionTitle,
        sessionIdRef,
        adoptSession,
        restoreMessages,
        reloadSession,
        openSession,
        newServerChat};
}
