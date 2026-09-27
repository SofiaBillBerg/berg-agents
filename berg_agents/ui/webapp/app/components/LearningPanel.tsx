import { Card, Chip, ProgressBar, Separator } from "@heroui/react";

export interface OutcomeRecord {
  success?: number;
  failure?: number;
}

export interface LearningStats {
  total?: number;
  by_task_type?: Record<string, OutcomeRecord>;
  by_model?: Record<string, OutcomeRecord>;
}

export interface LearningPanelProps {
  stats?: LearningStats | null;
  compact?: boolean;
}

/**
 * Success rate (0-100) for one outcome record.
 *
 * @param data - Outcome record with success/failure counts
 * @returns Rounded percentage of successful outcomes
 */
function successRate(data: OutcomeRecord | undefined): number {
  const success = data?.success || 0;
  const failure = data?.failure || 0;
  const total = success + failure;
  return total > 0 ? Math.round((success / total) * 100) : 0;
}

/**
 * Total outcomes recorded for one outcome record.
 *
 * @param data - Outcome record with success/failure counts
 * @returns Sum of successes and failures
 */
function outcomeTotal(data: OutcomeRecord | undefined): number {
  return (data?.success || 0) + (data?.failure || 0);
}

interface StatRowProps {
  label: string;
  rate: number;
  total: number;
  color: "accent" | "success";
}

/**
 * One labeled success-rate row with an accessible HeroUI progress bar.
 *
 * @param props - Row properties
 * @returns JSX element rendering the stat row
 */
function StatRow({ label, rate, total, color }: StatRowProps) {
  return (
    <div className="my-1 flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 truncate">{label}</span>
      <ProgressBar
        aria-label={`${label} success rate`}
        className="min-w-0 flex-1"
        color={color}
        size="sm"
        value={rate}
      >
        <ProgressBar.Track>
          <ProgressBar.Fill />
        </ProgressBar.Track>
      </ProgressBar>
      <span className="w-16 shrink-0 text-right text-muted tabular-nums">
        {rate}% ({total})
      </span>
    </div>
  );
}

/**
 * LearningPanel component.
 * Displays outcome statistics, success rates, and model performance metrics
 * gathered by the learning engine.
 *
 * @param props - Component properties
 * @returns JSX element rendering the learning stats panel
 */
export function LearningPanel({ stats, compact = false }: LearningPanelProps) {
  if (!stats || !stats.total || stats.total === 0) {
    return (
      <section aria-label="Learning stats" className="learning-panel empty">
        <Card>
          <Card.Header>
            <Card.Title>Learning Stats</Card.Title>
          </Card.Header>
          <Card.Content>
            <Card.Description>
              Nothing learned yet — run a task and this panel will show what
              worked, per task type and model.
            </Card.Description>
          </Card.Content>
        </Card>
      </section>
    );
  }

  const byTaskType = stats.by_task_type || {};
  const byModel = stats.by_model || {};

  if (compact) {
    return (
      <div
        aria-label="Learning stats"
        className="learning-panel compact flex flex-wrap items-center gap-2 text-xs"
      >
        <Chip size="sm" variant="primary">
          {stats.total} tasks
        </Chip>
        {Object.entries(byModel).map(([model, data]) => (
          <Chip key={model} size="sm" variant="soft">
            {model}: {successRate(data)}%
          </Chip>
        ))}
      </div>
    );
  }

  return (
    <section aria-label="Learning stats" className="learning-panel">
      <Card>
        <Card.Header>
          <Card.Title>Learning Stats</Card.Title>
          <Card.Description>
            Total tasks evaluated: {stats.total}
          </Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-3">
          {Object.keys(byTaskType).length > 0 && (
            <div>
              <h5 className="m-0 mb-1.5 text-xs font-semibold tracking-wider text-muted uppercase">
                By Task Type
              </h5>
              {Object.entries(byTaskType).map(([type, data]) => (
                <StatRow
                  key={type}
                  color="accent"
                  label={type}
                  rate={successRate(data)}
                  total={outcomeTotal(data)}
                />
              ))}
            </div>
          )}

          {Object.keys(byTaskType).length > 0 &&
            Object.keys(byModel).length > 0 && <Separator />}

          {Object.keys(byModel).length > 0 && (
            <div>
              <h5 className="m-0 mb-1.5 text-xs font-semibold tracking-wider text-muted uppercase">
                By Model
              </h5>
              {Object.entries(byModel).map(([model, data]) => (
                <StatRow
                  key={model}
                  color="success"
                  label={model}
                  rate={successRate(data)}
                  total={outcomeTotal(data)}
                />
              ))}
            </div>
          )}
        </Card.Content>
      </Card>
    </section>
  );
}

export default LearningPanel;
