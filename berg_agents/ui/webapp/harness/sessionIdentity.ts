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
 * The active session id - the one piece of chat state that outlives the tab.
 *
 * The server owns the conversation; this key is only how a reload or a
 * second window finds it again. Every reader and writer of the key goes
 * through here: the chat hook, the history page and the transport's
 * session adoption each used to touch localStorage directly, which meant
 * three copies of the same private-mode guard and three places where a
 * change to the key or the fallback could silently miss a caller.
 *
 * The id is written on adopt and cleared when the server says the stored
 * session is gone; it is never invented client-side (a second id format
 * is how one conversation became two).
 */

/** localStorage key for the active server-side session id. */
export const SESSION_ID_KEY = "berg_session_id";

/**
 * Read the stored session id, or null when there is none.
 *
 * @returns The id this tab should resume, or null on a first visit or
 *     when storage is unavailable.
 */
export function readStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_ID_KEY);
  } catch {
    // Storage blocked (private mode, disabled cookies): the server
    // session is still reachable by its own id within this tab.
    return null;
  }
}

/**
 * Store the active session id so a reload resumes it.
 *
 * @param id - The server-side session id to remember.
 */
export function storeSessionId(id: string): void {
  try {
    localStorage.setItem(SESSION_ID_KEY, id);
  } catch {
    // Private mode - the id stays in memory only, and the chat
    // keeps working for this tab.
  }
}

/**
 * Forget the stored session id, so a dead session is never retried.
 *
 * Called when the server reports the stored session no longer exists:
 * without it, every mount would retry a deleted id and the first send
 * would resurrect it through the backend's lazy row-create.
 */
export function forgetStoredSessionId(): void {
  try {
    localStorage.removeItem(SESSION_ID_KEY);
  } catch {
    // Nothing to forget when storage is unreachable.
  }
}
