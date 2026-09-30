"use client";

import { useEffect, useState } from "react";

import { Button, Card, Chip } from "@heroui/react";

import { CHAT_MESSAGES_KEY } from "@/harness/useAISDKChat";

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

/**
 * Sidebar widget that snapshots the live chat into localStorage and
 * restores snapshots back into it. Sessions persist across tab
 * switches and reloads; selecting one replaces the live conversation.
 */
export const ConversationHistory = ({ onSelect }: ConversationHistoryProps) => {
  const [sessions, setSessions] = useState<ChatSnapshot[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) setSessions(parsed as ChatSnapshot[]);
    } catch {
      // Corrupt storage — start empty.
    }
  }, []);

  const persist = (next: ChatSnapshot[]) => {
    setSessions(next);
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next.slice(0, 50)));
    } catch {
      // Quota exceeded — keep in-memory state only.
    }
  };

  const saveCurrent = () => {
    const messages = readLiveMessages();
    if (messages.length === 0) return;
    const snapshot: ChatSnapshot = {
      id: `${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
      title: snapshotTitle(messages),
      timestamp: new Date().toISOString(),
      messages: messages.slice(-200)};
    persist([snapshot, ...sessions]);
  };

  const restore = (session: ChatSnapshot) => {
    try {
      localStorage.setItem(CHAT_MESSAGES_KEY, JSON.stringify(session.messages));
    } catch {
      // Quota exceeded — still restore in memory.
    }
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
        <Button size="sm" variant="secondary" onPress={saveCurrent}>
          💾 Save chat
        </Button>
      </Card.Header>
      <Card.Content className="flex flex-col gap-1.5">
        {sessions.length === 0 && (
          <Card.Description>
            No saved chats yet — hit “Save chat” to snapshot this one.
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
