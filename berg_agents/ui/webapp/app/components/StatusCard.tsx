/*
 * StatusCard component — HeroUI v3 optimized status indicator using compound components.
 * Replaces basic status divs with proper Card compound pattern.
 */

import { Card } from "@heroui/react";

export interface StatusCardProps {
  status: {
    label: string;
    color: string;
    pulse: boolean;
  };
  isConnected: boolean;
  connectionError: string | null;
}

/**
 * StatusCard component.
 * Idle/streaming renders as one slim inline row (no card chrome) so
 * the conversation keeps the vertical space. Errors keep the full
 * card so the message stays readable and reportable.
 */
export function StatusCard({
  status,
  isConnected,
  connectionError}: StatusCardProps) {
  if (isConnected && !connectionError) {
    return (
      <div className="mb-2 flex items-center gap-2 px-1">
        <span
          className={`w-2 h-2 rounded-full ${status.pulse ? "animate-pulse" : ""}`}
          style={{ background: status.color }}
        />
        <span className="text-xs text-muted-foreground">{status.label}</span>
      </div>
    );
  }

  // Error state: the last chat request failed (backend down, model
  // unreachable, tool error). There is no mock/limited mode — say so
  // plainly and keep the message so it can be reported.
  return (
    <Card className="mb-4 border-yellow-200" variant="secondary">
      <Card.Header>
        <Card.Title className="text-yellow-800">
          {connectionError ? "Request Failed" : "Connection Warning"}
        </Card.Title>
      </Card.Header>
      <Card.Content>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${status.pulse ? "animate-pulse" : ""}`}
            style={{ background: status.color }}
          />
          <span className="text-sm text-yellow-700">
            {isConnected
              ? "The backend answered with an error — see details below."
              : "Cannot reach the backend at :8001. Is `uv run berg_agents --web` running?"}
          </span>
          {connectionError && (
            <span className="text-xs text-red-600">
              Error: {connectionError}
            </span>
          )}
        </div>
      </Card.Content>
    </Card>
  );
}

export default StatusCard;
