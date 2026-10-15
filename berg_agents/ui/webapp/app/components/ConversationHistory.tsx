/*
 * Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"use client";

import { useEffect, useState } from "react";
import { Button, Card, Chip } from "@heroui/react";

import {
  CHAT_MESSAGES_KEY,
  slimUIMessagesForPersist} from "@/harness/useAISDKChat";

/** localStorage key for named snapshots (live chat key lives in the hook). */
const HISTORY_KEY = "berg_agents_chat_history";

/** One saved conversation snapshot. */
export interface ChatSnapshot {
  id: string;
  title: string;
  timestamp: string;
  messages: unknown[];
}

interface ConversationHistoryProps {
  /** Restore a snapshot's messages into the live chat */
  onSelect: (messages: unknown[]) => void;
}

/** Read the live conversation the chat hook persists. */
function readLiveMessages(): unknown[] {
  try {
    const raw = localStorage.getItem(CHAT_MESSAGES_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Derive a short title from the first user text part found. */
function snapshotTitle(messages: unknown[]): string {
  for (const m of messages) {
    if (typeof m !== "object" || m === null) continue;
    const msg = m as { role?: unknown; parts?: unknown };
    if (msg.role !== "user" || !Array.isArray(msg.parts)) continue;
    for (const p of msg.parts) {
      if (
        typeof p === "object" &&
        p !== null &&
        (p as { type?: unknown }).type === "text" &&
        typeof (p as { text?: unknown }).text === "string"
      ) {
        const text = ((p as { text: string }).text || "").trim();
        if (text) return text.slice(0, 60);
      }
    }
  }
  return "Untitled conversation";
}

/** Read all saved snapshots (newest first). */
export function readSnapshots(): ChatSnapshot[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as ChatSnapshot[]) : [];
  } catch {
    return [];
  }
}

/** Persist snapshots (newest first, capped, slimmed for quota safety). */
export function writeSnapshots(sessions: ChatSnapshot[]): void {
  try {
    const slimmed = sessions.slice(0, 50).map((s) => ({
      ...s,
      messages: slimUIMessagesForPersist(
        Array.isArray(s.messages) ? s.messages : [],
      )}));
    localStorage.setItem(HISTORY_KEY, JSON.stringify(slimmed));
  } catch {
    // Quota exceeded - in-memory state is the caller's job.
  }
}

/**
 * Snapshot the live conversation into history (resumable session).
 * Returns the snapshot, or null when there is nothing to save.
 * Skips duplicates: when the newest snapshot already holds the same
 * messages, it is returned untouched instead of saving twice.
 */
export function snapshotLiveChat(): ChatSnapshot | null {
  const messages = readLiveMessages();
  if (messages.length === 0) return null;
  const sessions = readSnapshots();
  const newest = sessions[0];
  try {
    if (
      newest &&
      JSON.stringify(newest.messages) === JSON.stringify(messages)
    ) {
      return newest;
    }
  } catch {
    // Unserializable - fall through and save anyway.
  }
  const snapshot: ChatSnapshot = {
    id: `${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
    title: snapshotTitle(messages),
    timestamp: new Date().toISOString(),
    messages: messages.slice(-200)};
  writeSnapshots([snapshot, ...sessions]);
  return snapshot;
}

/**
 * Park the live chat, then stage snapshot messages as the live
 * conversation (slimmed for quota safety). Callers navigate to `/`
 * (chat restores from the live key on mount) or feed the messages to
 * the live hook directly.
 *
 * @param messages - Snapshot messages to stage.
 */
export function restoreSnapshotToLive(messages: unknown[]): void {
  // Never lose the live conversation: park it first (deduped).
  snapshotLiveChat();
  try {
    localStorage.setItem(
      CHAT_MESSAGES_KEY,
      JSON.stringify(
        slimUIMessagesForPersist(Array.isArray(messages) ? messages : []),
      ),
    );
  } catch {
    // Quota exceeded - callers still restore in memory.
  }
}

/**
 * Sidebar widget that snapshots the live chat into localStorage and
 * restores snapshots back into it. Sessions persist across tab
 * switches and reloads; selecting one replaces the live conversation.
 */
export const ConversationHistory = ({ onSelect }: ConversationHistoryProps) => {
  const [sessions, setSessions] = useState<ChatSnapshot[]>([]);

  useEffect(() => {
    const reread = () => setSessions(readSnapshots());
    try {
      reread();
    } catch {
      // Corrupt storage - start empty.
    }
    // NOTE: Snapshots written from another tab (e.g. the /history
    // page) never re-render this widget otherwise — same browser,
    // different answer. The storage event fires only in the tabs
    // that did NOT write, which is exactly the stale ones.
    window.addEventListener("storage", reread);
    return () => window.removeEventListener("storage", reread);
  }, []);

  const persist = (next: ChatSnapshot[]) => {
    setSessions(next);
    // NOTE: Slimmed via writeSnapshots (quota safety).
    writeSnapshots(next);
  };

  const saveCurrent = () => {
    const snapshot = snapshotLiveChat();
    if (snapshot) setSessions(readSnapshots());
  };

  const restore = (session: ChatSnapshot) => {
    // Never lose the live conversation: park it as a session first
    // (deduped inside snapshotLiveChat) before replacing it.
    restoreSnapshotToLive(session.messages);
    setSessions(readSnapshots());
    onSelect(session.messages);
  };

  const remove = (id: string) => {
    persist(sessions.filter((s) => s.id !== id));
  };

  return (
    <Card variant="default">
      <Card.Header className="flex items-center gap-2">
        <Card.Title>History</Card.Title>
        <span className="flex-1" />
        <span title="Snapshot this conversation into History (stays in the browser, restorable any time)">
          <Button size="sm" variant="secondary" onPress={saveCurrent}>
            💾 Save to history
          </Button>
        </span>
      </Card.Header>
      <Card.Content className="flex flex-col gap-1.5">
        {sessions.length === 0 && (
          <Card.Description>
            No saved chats yet - hit "Save chat" to snapshot this one.
          </Card.Description>
        )}
        {sessions.map((s) => (
          <div key={s.id} className="flex items-center gap-2">
            <Button
              className="flex-1 justify-start"
              size="sm"
              variant="secondary"
              onPress={() => restore(s)}
            >
              <span className="truncate">{s.title}</span>
            </Button>
            <Chip size="sm" variant="soft">
              {new Date(s.timestamp).toLocaleDateString()}
            </Chip>
            <Button size="sm" variant="secondary" onPress={() => remove(s.id)}>
              ✕
            </Button>
          </div>
        ))}
      </Card.Content>
    </Card>
  );
};

export default ConversationHistory;
