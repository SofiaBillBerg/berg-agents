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

import {useState} from "react";

export interface ToolCardProps {
  /** Name of the tool (e.g. 'read_file', 'run_task') */
  tool: string;
  /** Raw input argument string (optional) */
  input?: string;
  /** Output from the tool (any JSON-serializable value) */
  output?: unknown;
  /** Whether the card starts expanded */
  expanded?: boolean;
  /** Tool execution state (e.g. "output-available", "approval-requested") */
  state?: string;
  /** Callback to toggle expansion (optional) */
  onToggle?: () => void;
}

/**
 * Compact collapsible row for one tool call and its result.
 * Collapsed it is a single slim line (label + status + two small
 * buttons) so stacked calls take ~15% of the old card space.
 * Expanded output scrolls inside a capped box so one big result
 * can never push the conversation out of view.
 */
export const ToolCard = ({
  tool,
  input,
  output,
  expanded,
  state,
  onToggle}: ToolCardProps) => {
  const [open, setOpen] = useState(expanded ?? false);
  const [copied, setCopied] = useState(false);

  const toggle = () => {
    setOpen((prev) => !prev);
    onToggle?.();
  };

  const outputText =
    typeof output === "string" ? output : JSON.stringify(output, null, 2);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(outputText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (permissions, insecure context) - no-op.
    }
  };

  return (
    <div className="rounded-md border border-border bg-surface-soft/50">
      <div className="flex items-center gap-2 px-2 py-1">
        <span className="font-mono text-xs truncate" title={tool}>
          🔧 {tool}
        </span>
        {state && (
          <span className="text-[11px] text-muted-foreground shrink-0">
            · {state}
          </span>
        )}
        <span className="flex-1" />
        <button
          aria-label={open ? `Hide ${tool} details` : `Show ${tool} details`}
          className="text-[11px] text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
          onClick={toggle}
          type="button"
        >
          {open ? "Hide" : "Show"}
        </button>
        {output !== undefined && (
          <button
            aria-label={`Copy ${tool} output`}
            className="text-[11px] text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
            onClick={copy}
            type="button"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        )}
      </div>
      {open && (
        <div className="flex flex-col gap-1 px-2 pb-1.5">
          {input && (
            <pre className="font-mono bg-surface-soft p-1.5 rounded text-[11px] overflow-auto max-h-40 whitespace-pre-wrap">
              {input}
            </pre>
          )}
          {output !== undefined && (
            <pre className="font-mono bg-surface-soft p-1.5 rounded text-[11px] overflow-auto max-h-64 whitespace-pre-wrap">
              {outputText}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};

export default ToolCard;
