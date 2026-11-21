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

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";

export interface OutcomeRecord {
  success?: number;
  failure?: number;
}

export interface RouterStats {
  total?: number;
  by_task_type?: Record<string, OutcomeRecord>;
  by_model?: Record<string, OutcomeRecord>;
}

export interface RouterStatsPanelProps {
  stats?: RouterStats | null;
  compact?: boolean;
}

/**
 * Success rate (0-100) for one outcome record.
 */
function successRate(data: OutcomeRecord | undefined): number {
  const success = data?.success || 0;
  const failure = data?.failure || 0;
  const total = success + failure;
  return total > 0 ? Math.round((success / total) * 100) : 0;
}

/**
 * Total outcomes recorded for one outcome record.
 */
function outcomeTotal(data: OutcomeRecord | undefined): number {
  return (data?.success || 0) + (data?.failure || 0);
}

interface StatRowProps {
  label: string;
  rate: number;
  total: number;
  tone: "accent" | "success";
}

/**
 * One labeled success-rate row with an accessible progress bar.
 */
function StatRow({ label, rate, total, tone }: StatRowProps) {
  return (
    <div className="my-1 flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 truncate" title={label}>
        {label}
      </span>
      <Progress
        aria-label={`${label} success rate`}
        className={`h-1.5 min-w-0 flex-1 ${
          tone === "success"
            ? "[&_[data-slot=progress-indicator]]:bg-emerald-600"
            : ""
        }`}
        value={rate}
      />
      <span className="w-16 shrink-0 text-right text-muted-foreground tabular-nums">
        {rate}% ({total})
      </span>
    </div>
  );
}

/**
 * RouterStatsPanel component.
 * Displays outcome statistics, success rates, and model performance metrics
 * gathered by the router engine.
 */
export function RouterStatsPanel({
  stats,
  compact = false}: RouterStatsPanelProps) {
  if (!stats || !stats.total || stats.total === 0) {
    return (
      <section aria-label="Router stats" className="router-stats empty">
        <Card>
          <CardHeader>
            <CardTitle>Router Stats</CardTitle>
            <CardDescription>
              Nothing learned yet — run a task and this panel will show what
              worked, per task type and model.
            </CardDescription>
          </CardHeader>
        </Card>
      </section>
    );
  }

  const byTaskType = stats.by_task_type || {};
  const byModel = stats.by_model || {};

  if (compact) {
    return (
      <div
        aria-label="Router stats"
        className="router-stats-panel compact flex flex-wrap items-center gap-1.5 text-xs"
      >
        <Badge variant="default">{stats.total} tasks</Badge>
        {Object.entries(byModel).map(([model, data]) => (
          <Badge key={model} variant="secondary">
            {model}: {successRate(data)}%
          </Badge>
        ))}
      </div>
    );
  }

  return (
    <section aria-label="Router stats" className="router-stats-panel">
      <Card>
        <CardHeader>
          <CardTitle>Router Stats</CardTitle>
          <CardDescription>
            Total tasks evaluated: {stats.total}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {Object.keys(byTaskType).length > 0 && (
            <div>
              <h5 className="m-0 mb-1.5 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                By Task Type
              </h5>
              {Object.entries(byTaskType).map(([type, data]) => (
                <StatRow
                  key={type}
                  label={type}
                  rate={successRate(data)}
                  tone="accent"
                  total={outcomeTotal(data)}
                />
              ))}
            </div>
          )}

          {Object.keys(byTaskType).length > 0 &&
            Object.keys(byModel).length > 0 && <Separator />}

          {Object.keys(byModel).length > 0 && (
            <div>
              <h5 className="m-0 mb-1.5 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                By Model
              </h5>
              {Object.entries(byModel).map(([model, data]) => (
                <StatRow
                  key={model}
                  label={model}
                  rate={successRate(data)}
                  tone="success"
                  total={outcomeTotal(data)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export default RouterStatsPanel;
