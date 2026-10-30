/*
 * Berg Agents is a sophisticated multi-agent system built with modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "@/envConfig";

interface UsageReading {
  used_tokens: number;
  window_tokens: number;
  fraction: number;
  resolved: boolean;
}

/** How often to refresh while a turn is running, in ms. */
const POLL_MS = 4000;

/**
 * Live context-window gauge.
 *
 * The harness emits `ContextUsageEvent` on every model request; the
 * backend serves the latest reading. Without this the user only learned
 * the context was full when compaction silently shortened their history.
 *
 * Tone is driven by the fraction (matching the project's status colours)
 * and `~` marks an unresolved window — the harness's fallback rather than
 * the model's real one, so the number is a good guess and says so.
 */
export default function ContextGauge({
  sessionId,
  streaming}: {
  sessionId: string | null;
  streaming: boolean;
}) {
  const [usage, setUsage] = useState<UsageReading | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(
        `${API_BASE}/api/context/usage` +
          (sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""),
      );
      if (!resp.ok) return;
      const data = await resp.json();
      setUsage(data?.usage ?? null);
    } catch {
      // Backend unreachable - keep the last reading.
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while a turn runs (the reading changes every request), then a
  // few more times so the final number settles.
  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [streaming, refresh]);

  if (!usage || usage.window_tokens <= 0) return null;

  const pct = Math.min(100, Math.max(0, Math.round(usage.fraction * 100)));
  const tone =
    pct >= 90
      ? "var(--danger, #ef4444)"
      : pct >= 75
        ? "var(--warning, #f59e0b)"
        : "var(--success, #22c55e)";
  const guess = usage.resolved ? "" : "~";

  return (
    <span
      aria-label={`Context window ${pct} percent full`}
      className="flex items-center gap-1.5 text-xs text-muted-foreground"
      title={
        `${guess}${pct}% of ${guess}${usage.window_tokens.toLocaleString()} tokens` +
        ` used (${usage.used_tokens.toLocaleString()})` +
        (usage.resolved
          ? ""
          : " — window size is estimated, not the model's real one")
      }
    >
      <span
        aria-hidden
        className="relative h-1.5 w-12 overflow-hidden rounded-full"
        style={{ background: "var(--muted)" }}
      >
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: tone }}
        />
      </span>
      <span className="tabular-nums">
        {guess}
        {pct}%
      </span>
    </span>
  );
}
