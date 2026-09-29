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
 * StatusCard component using HeroUI v3 Card compound components.
 * Shows connection status with proper visual hierarchy.
 */
export function StatusCard({
  status,
  isConnected,
  connectionError}: StatusCardProps) {
  if (isConnected && !connectionError) {
    return (
      <Card className="mb-4" variant="default">
        <Card.Content className="flex items-center gap-2 p-3">
          <span
            className={`w-2 h-2 rounded-full ${status.pulse ? "animate-pulse" : ""}`}
            style={{ background: status.color }}
          />
          <span className="text-sm">{status.label}</span>
        </Card.Content>
      </Card>
    );
  }

  return (
    <Card className="mb-4 border-yellow-200" variant="secondary">
      <Card.Header>
        <Card.Title className="text-yellow-800">Connection Warning</Card.Title>
      </Card.Header>
      <Card.Content>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${status.pulse ? "animate-pulse" : ""}`}
            style={{ background: status.color }}
          />
          <span className="text-sm text-yellow-700">
            Running in {isConnected ? "mock" : "limited"} mode
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
