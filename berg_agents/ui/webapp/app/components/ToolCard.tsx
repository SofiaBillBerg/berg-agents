'use client';

import { useState } from "react";

import { Button, Card } from "@heroui/react";

export interface ToolCardProps {
  /** Name of the tool (e.g. 'read_file', 'run_task') */
  tool: string;
  /** Raw input argument string (optional) */
  input?: string;
  /** Output from the tool (any JSON-serializable value) */
  output?: unknown;
  /** Whether the card starts expanded */
  expanded?: boolean;
  /** Callback to toggle expansion (optional) */
  onToggle?: () => void;
}

/**
 * Collapsible card that displays one tool call and its result.
 * Uses only HeroUI v3 compound components (Card.Header/Content) plus
 * a plain <pre> for output and the Clipboard API for copying.
 */
export const ToolCard = ({
  tool,
  input,
  output,
  expanded,
  onToggle}: ToolCardProps) => {
  const [open, setOpen] = useState(expanded ?? true);
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
      // Clipboard unavailable (permissions, insecure context) — no-op.
    }
  };

  return (
    <Card variant="default">
      <Card.Header className="flex items-center gap-2">
        <span className="font-mono text-sm">🔧 {tool}</span>
        <span className="flex-1" />
        <Button size="sm" variant="secondary" onPress={toggle}>
          {open ? "Hide" : "Show"}
        </Button>
        {output !== undefined && (
          <Button size="sm" variant="secondary" onPress={copy}>
            {copied ? "Copied!" : "Copy"}
          </Button>
        )}
      </Card.Header>
      {open && (
        <Card.Content className="flex flex-col gap-2">
          {input && (
            <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto">
              {input}
            </pre>
          )}
          {output !== undefined && (
            <pre className="font-mono bg-surface-soft p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap">
              {outputText}
            </pre>
          )}
        </Card.Content>
      )}
    </Card>
  );
};

export default ToolCard;
