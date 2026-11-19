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

/* History page - searchable archive of conversations.
 *
 * Server sessions first (SQLite, shared across browsers via
 * /api/sessions with full-text search), local snapshots as fallback
 * Restoring adopts the session project-wide, so other windows converge.
 * transcript as live, and returns to `/`.
 */

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  RiCheckLine,
  RiDeleteBinLine,
  RiEditLine,
  RiRestartLine} from "@remixicon/react";

import { Navbar } from "../components/Navbar.tsx";

import { Badge } from "@/components/ui/badge.tsx";
import { Button } from "@/components/ui/button.tsx";
import { ScrollArea } from "@/components/ui/scroll-area.tsx";
import { Tooltip, TooltipTrigger } from "@/components/ui/tooltip.tsx";
import { API_BASE } from "@/envConfig";
import { storeSessionId } from "@/harness/sessionIdentity";

interface ServerSession {
  id: string;
  title: string;
  subtitle: string;
  workspace: string;
  updated_at: string;
  message_count: number;
  model: string | null;
  outcome: string;
}

/** HistoryPage - server-side sessions, searchable. */
export default function HistoryPage() {
  const router = useRouter();
  const [serverSessions, setServerSessions] = useState<ServerSession[] | null>(
    null,
  );
  const [restoredMessages, setRestoredMessages] = useState<unknown[] | null>(
    null,
  );
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  // Server search (debounced): titles, subtitles, transcripts.
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const resp = await fetch(
          `${API_BASE}/api/sessions?q=${encodeURIComponent(query.trim())}`,
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!cancelled && Array.isArray(data.sessions)) {
          setServerSessions(data.sessions);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setServerSessions(null);
          setError(query.trim() ? String(e) : null);
        }
      }
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const refreshServer = async () => {
    try {
      const resp = await fetch(
        `${API_BASE}/api/sessions?q=${encodeURIComponent(query.trim())}`,
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (Array.isArray(data.sessions)) setServerSessions(data.sessions);
    } catch (e) {
      setError(String(e));
    }
  };

  const restoreServer = async (session: ServerSession) => {
    const resp = await fetch(
      `${API_BASE}/api/sessions/${encodeURIComponent(session.id)}`,
    );
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    setRestoredMessages(Array.isArray(data.messages) ? data.messages : []);
    storeSessionId(session.id);
    // NOTE: Restoring adopts project-wide, so other windows converge.
    await fetch(`${API_BASE}/api/sessions/current`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: session.id })}).catch(() => undefined);
    router.push("/");
  };

  void restoredMessages;

  const removeServer = async (id: string) => {
    await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE"});
    await refreshServer();
  };

  const renameServer = async (id: string) => {
    const title = draftTitle.trim();
    if (!title) return;
    const resp = await fetch(
      `${API_BASE}/api/sessions/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title })},
    );
    if (resp.ok) {
      setRenamingId(null);
      await refreshServer();
    }
  };

  return (
    <>
      <Navbar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl p-4">
          <h1 className="text-2xl font-bold mb-4">History</h1>
          <p className="text-sm text-muted-foreground mb-4">
            Sessions are saved server-side, so they are the same in every
            browser. Each one is also written to a durable JSONL transcript on
            disk, so history survives the database.
          </p>
          <input
            aria-label="Search conversations"
            className="mb-3 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            id="session-search"
            name="session-search"
            placeholder="Search titles, subtitles, transcripts…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {error && <p className="mb-2 text-xs text-red-500">{error}</p>}

          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            Server sessions
            {serverSessions ? ` (${serverSessions.length})` : ""}
            <span className="flex-1" />
            <Button
              aria-label="Refresh server sessions"
              size="sm"
              variant="secondary"
              onPress={() => void refreshServer()}
            >
              ↻
            </Button>
          </h2>
          {serverSessions === null && !error && (
            <p className="mb-3 text-xs text-muted-foreground">Loading…</p>
          )}
          <ScrollArea className="max-h-[70vh]">
            <ul className="flex flex-col">
              {(serverSessions ?? []).map((s) => (
                <li
                  key={s.id}
                  className="flex items-center gap-2 px-1 py-1 text-xs"
                >
                  {/* Title first, and the whole row is the thing: this used
                        to be a Card per session — a box around two lines of
                        text and four buttons, which pushed a page of history
                        into a wall of chrome. The subtitle and counts stay,
                        in the row, at caption weight. */}
                  <span className="min-w-0 flex-1 truncate">
                    {renamingId === s.id ? (
                      <input
                        aria-label="Session title"
                        className="w-full rounded-md border border-border bg-background px-1 py-0.5 text-sm"
                        value={draftTitle}
                        onChange={(e) => setDraftTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void renameServer(s.id);
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                      />
                    ) : (
                      <span className="font-medium">{s.title}</span>
                    )}
                    <span className="ml-2 opacity-60">
                      {s.subtitle || s.workspace}
                    </span>
                  </span>
                  <Badge variant="outline">{s.workspace}</Badge>
                  <time className="opacity-60 tabular-nums">
                    {new Date(s.updated_at).toLocaleString()} ·{" "}
                    {s.message_count} msgs
                  </time>
                  {renamingId === s.id ? (
                    <TooltipTrigger>
                      <Button
                        aria-label="Save title"
                        size="xs"
                        variant="ghost"
                        onPress={() => void renameServer(s.id)}
                      >
                        <RiCheckLine data-icon="inline-start" />
                      </Button>
                      <Tooltip placement="top">Save title</Tooltip>
                    </TooltipTrigger>
                  ) : (
                    <TooltipTrigger>
                      <Button
                        aria-label={`Rename ${s.title}`}
                        size="xs"
                        variant="ghost"
                        onPress={() => {
                          setRenamingId(s.id);
                          setDraftTitle(s.title);
                        }}
                      >
                        <RiEditLine data-icon="inline-start" />
                      </Button>
                      <Tooltip placement="top">Rename</Tooltip>
                    </TooltipTrigger>
                  )}
                  <TooltipTrigger>
                    <Button
                      aria-label={`Restore ${s.title}`}
                      size="xs"
                      variant="ghost"
                      onPress={() => void restoreServer(s)}
                    >
                      <RiRestartLine data-icon="inline-start" />
                    </Button>
                    <Tooltip placement="top">Restore this conversation</Tooltip>
                  </TooltipTrigger>
                  <TooltipTrigger>
                    <Button
                      aria-label={`Delete ${s.title}`}
                      size="xs"
                      variant="ghost"
                      onPress={() => void removeServer(s.id)}
                    >
                      <RiDeleteBinLine data-icon="inline-start" />
                    </Button>
                    <Tooltip placement="top">Delete this conversation</Tooltip>
                  </TooltipTrigger>
                </li>
              ))}
              {serverSessions !== null && serverSessions.length === 0 && (
                <li className="px-1 py-2 text-xs opacity-60">
                  No server sessions yet — chat once and it appears here in
                  every browser.
                </li>
              )}
            </ul>
          </ScrollArea>
        </div>
      </div>
    </>
  );
}
